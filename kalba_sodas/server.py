"""One local web app: Žemė (/zeme: datasets and LKEŽDB), the research garden (/), Vaiva studies (/vaiva) and the
settings (/nustatymai) share a server, theme and header. One person works with it on their own computer: everything
is theirs, nobody signs in."""
from __future__ import annotations

import re
import threading
import traceback
import webbrowser
from http.server import ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from kalba_import.import_all import read_datasets_config
from kalba_import.neo4j_config import neo4j_settings
from kalba_import.ui_server import UIState, make_handler

from . import apie, bibliografija, i18n, sekimas
from .graph import Graph
from .rysiai import Relationships
from .store import Store
from .vaiva import STUDIES, Vaiva, dirbtuves, study_list
from kalba_lkezdb import DEFAULT_DB as LKEZDB_DB
from kalba_lkezdb.service import Lkezdb

H, J, C, S = "text/html; charset=utf-8", "application/javascript; charset=utf-8", "text/css; charset=utf-8", "image/svg+xml"
STATIC = {"/": ("sodas.html", H), "/nustatymai": ("sodas.html", H), "/vaiva": ("vaiva.html", H), "/lkezdb": ("lkezdb.html", H),
          "/zeme": ("zeme.html", H),
          "/sodas/lkezdb.js": ("lkezdb.js", J), "/sodas/vaiva.js": ("vaiva.js", J), "/sodas/vaiva.css": ("vaiva.css", C),
          "/sodas/dirbtuves.js": ("dirbtuves.js", J), "/sodas/dirbtuves.css": ("dirbtuves.css", C),
          "/sodas/sodas.css": ("sodas.css", C), "/sodas/sodas.js": ("sodas.js", J), "/sodas/theme.js": ("theme.js", J),
          "/sodas/theme.css": ("theme.css", C), "/sodas/leaflet.js": ("leaflet.js", J), "/sodas/leaflet.css": ("leaflet.css", C),
          "/sodas/bar.js": ("bar.js", J), "/sodas/pamoka.js": ("pamoka.js", J), "/sodas/zeme.js": ("zeme.js", J),
          "/sodas/i18n.js": ("i18n.js", J),
          "/sodas/ikonos/zenklas.svg": ("ikonos/zenklas.svg", S), "/sodas/ikonos/zenkliukas.svg": ("ikonos/zenkliukas.svg", S),
          "/favicon.ico": ("ikonos/zenkliukas.svg", S)}
MAX_BODY = 32 * 1024 * 1024   # a garden of a few thousand nodes is a few MB


def bundle_source(desc: Any, depth: int = 0) -> dict[str, Any]:
    """A bundle as the browser sends it back ({source, type, out, name, label}; ``source`` a node or another bundle),
    checked for its shape (the names are checked again where they go into Cypher)."""
    if not isinstance(desc, dict) or depth > 3:
        raise ValueError("netinkamas pluoštas")
    src = desc.get("source")
    if isinstance(src, dict) and isinstance(src.get("bundle"), dict):
        src = {"bundle": bundle_source(src["bundle"], depth + 1)["bundle"]}
    elif isinstance(src, dict) and src.get("label") and src.get("key"):
        src = {"label": str(src["label"]), "key": str(src["key"])}
    else:
        raise ValueError("netinkamas pluošto šaltinis")
    return {"bundle": {"source": src, "type": str(desc.get("type") or ""), "out": bool(desc.get("out")),
                       "name": str(desc.get("name") or ""), "label": str(desc.get("label") or "")}}


class SodasApp:
    def __init__(self, store: Store, neo4j_config: Path, datasets_config: Path | None = None, lkezdb_db: Path | None = None):
        self.store = store
        self.graph = Graph(lambda: neo4j_settings(config_path=neo4j_config))
        self.rels = Relationships(store.root, self.graph)
        self.datasets_config = datasets_config
        db = lkezdb_db or ((datasets_config.parent if datasets_config else Path(".")) / LKEZDB_DB)
        self.lkezdb = Lkezdb(db, lambda: neo4j_settings(config_path=neo4j_config),
                             lambda level, source, message, detail=None: store.log(level, source, message, detail))
        if self.lkezdb.store.available and self.lkezdb.store.stats()["eileje"]:
            self.lkezdb.start_worker()   # jobs left in the queue by a stopped server
        self.vaiva = Vaiva(store.root, lambda *a, **kw: self.graph.read(*a, **kw), self.dataset_paths,
                           lambda level, source, message, detail=None: store.log(level, source, message, detail))
        # which datasets every garden and every Vaiva run used (sekimas), for its bibliography
        store.dataset_versions = self.dataset_versions
        self.vaiva.dataset_versions = self.dataset_versions
        self.vaiva.known_datasets = lambda: set(bibliografija.CATALOGUE) | set(self.dataset_paths())

    def dataset_paths(self) -> dict[str, Path]:
        """Dataset directories (datasets.yaml), for files not in Neo4j such as etc/orthography.tsv."""
        if self.datasets_config is None or not self.datasets_config.exists():
            return {}
        return read_datasets_config(self.datasets_config)

    def dataset_versions(self) -> dict[str, dict[str, Any]]:
        return sekimas.dataset_versions(self.dataset_paths())

    def cff_paths(self) -> list[Path]:
        """Where SODAS's own CITATION.cff may be: next to datasets.yaml, or next to the program."""
        here = Path(__file__).resolve().parent.parent / bibliografija.CFF_NAME
        return ([self.datasets_config.parent / bibliografija.CFF_NAME] if self.datasets_config else []) + [here]

    def contact_paths(self) -> list[Path]:
        """Where kontaktai.yaml („Apie Sodą“) may be: next to datasets.yaml, or next to the program."""
        here = Path(__file__).resolve().parent.parent / apie.FILE_NAME
        return ([self.datasets_config.parent / apie.FILE_NAME] if self.datasets_config else []) + [here]

    # -- the bibliography of a garden or a Vaiva run -------------------------------------------------------
    def bibliography(self, q: dict[str, str]) -> dict[str, Any]:
        fmt = q.get("formatas") or "bibtex"
        if fmt not in bibliografija.FORMATS:
            raise ValueError(f"nežinomas formatas: {fmt}")
        entries, trial, approximate, name, what = self._bib_entries(q)
        f = bibliografija.FORMATS[fmt]
        slug = re.sub(r"[^\w]+", "_", name, flags=re.UNICODE).strip("_")[:60] or what
        return {"format": fmt, "formats": {k: v["title"] for k, v in bibliografija.FORMATS.items()},
                "text": bibliografija.render(fmt, entries), "filename": f"{slug}.{f['ext']}", "mime": f["mime"],
                "entries": bibliografija.summary(entries), "trial": trial, "approximate": approximate, "name": name, "what": what}

    def bibliography_all(self, q: dict[str, str]) -> dict[str, Any]:
        """Every format at once – what a downloaded garden (SVG, PNG, JSON) carries with it."""
        entries, trial, approximate, name, what = self._bib_entries(q)
        return {"tekstas": bibliografija.render("tekstas", entries), "bibtex": bibliografija.render("bibtex", entries),
                "ris": bibliografija.render("ris", entries), "csl": bibliografija.render("csl", entries),
                "entries": bibliografija.summary(entries), "trial": trial, "approximate": approximate, "name": name,
                "made_at": bibliografija.today()}

    def _bib_entries(self, q: dict[str, str]) -> tuple[list[dict[str, Any]], bool, bool, str, str]:
        """SODAS and the datasets a garden (``sodas``) or a Vaiva run (``tyrimas``) used; ``ir``: datasets the page shows
        besides (e.g. the map of a merged node, not saved with the garden), comma-separated, only known ones."""
        versions = self.dataset_versions()
        approximate = False
        if q.get("sodas"):
            g = self.store.garden(q["sodas"]) or {}
            name = g.get("name") or "Sodas"
            sources = sekimas.union_sources(g.get("sources"))
            if not sources and g.get("nodes"):       # saved before the use was followed: from the nodes in it now
                sources = sekimas.merge_sources(None, sekimas.garden_datasets(g), versions, g.get("updated_at"))
                approximate = True
            what = "sodas"
        elif q.get("tyrimas"):
            run = self.vaiva.get(q["tyrimas"])
            name = run.get("name") or run.get("title") or "Vaiva"
            sources = sekimas.union_sources(run.get("sources"))
            if "sources" not in run:                 # a run from before the use was followed
                found = {sekimas.dataset_of_key(n.get("key"), self.vaiva.known_datasets()) for n in run.get("nodes") or []}
                study = STUDIES.get(run.get("study"))
                found |= set(study.STUDY.get("datasets", ()) if study else ())
                for st in ((run.get("result") or {}).get("blocks") or {}).values():
                    found |= set(st.get("datasets") or [])
                sources = sekimas.merge_sources(None, {f for f in found if f}, versions, run.get("finished_at"))
                approximate = True
            what = "tyrimas"
        else:
            name, sources, what = "SODAS", {}, "sodas"
        extra = {d.strip() for d in str(q.get("ir") or "").split(",") if d.strip()} & self.vaiva.known_datasets()
        if extra - set(sources):
            sources = sekimas.merge_sources(sources, extra - set(sources), versions)
        own, trial = bibliografija.sodas_entries(self.cff_paths())
        entries = own + bibliografija.dataset_entries(sources, versions, self.dataset_paths())
        return entries, trial, approximate, name, what

    def refs(self, items: Any) -> list[dict[str, str]]:
        if not isinstance(items, list):
            raise ValueError("expected a list of {label, key}")
        return [{"label": str(i["label"]), "key": str(i["key"])} for i in items][:2000]

    def graph_now(self) -> Graph:
        """The graph without the datasets switched off (⚙ → Duomenynai)."""
        return self.graph.scoped(None, self.store.datasets_off())

    # -- GET ------------------------------------------------------------------------------
    def get(self, path: str, q: dict[str, str]) -> Any:
        g = self.graph_now()
        if path == "/api/sodas/settings":
            return self.store.settings()
        if path == "/api/sodas/status":
            return g.status()
        if path == "/api/sodas/schema":
            return g.schema()
        if path == "/api/sodas/log":
            return self.store.log_entries()
        if path == "/api/sodas/gardens":
            return {"gardens": self.store.gardens(), "new_id": self.store.new_garden_id()}
        if path.startswith("/api/sodas/gardens/") and path.endswith("/byla"):
            gid = path.split("/")[-2]
            out = self.store.garden_file(gid)
            # a garden file always carries the bibliography of what it uses
            return {**out, "bibliografija": self.bibliography_all({"sodas": gid})}
        if path == "/api/bibliografija/visa":
            return self.bibliography_all(q)
        if path == "/api/bibliografija":
            return self.bibliography(q)
        if path == "/api/apie":
            return apie.about(self.contact_paths())
        if path.startswith("/api/sodas/gardens/"):
            return self.store.garden(path.rsplit("/", 1)[-1]) or {}
        if path == "/api/sodas/rysiai":
            return {"relationships": self.rels.mine()}
        if path == "/api/sodas/rysiai/uzrasai":
            return {"labels": self.rels.my_labels()}
        if path.startswith("/api/sodas/rysiai/"):
            return self.rels.get(path.rsplit("/", 1)[-1])
        if path.startswith("/api/lkezdb/"):
            return self.lkezdb_get(path.removeprefix("/api/lkezdb/"), q)
        if path == "/api/vaiva/studies":
            return {"studies": study_list()}
        if path == "/api/vaiva/dirbtuves":
            return dirbtuves.workshop()
        if path == "/api/vaiva/runs":
            return {"runs": self.vaiva.runs()}
        if path == "/api/vaiva/juodrastis":
            return {"draft": self.store.draft("dirbtuves")}
        if path.startswith("/api/vaiva/runs/"):
            return self.vaiva.get(path.rsplit("/", 1)[-1])
        if path == "/api/sodas/types":
            return {"labels": g.label_counts()}
        if path == "/api/sodas/label-types":
            return {"label": q["label"], "types": g.label_rel_types(q["label"])}
        if path == "/api/sodas/properties":
            names = sorted({c["name"] for c in self.store.settings()["computed"] if c.get("label") == q["label"] and c.get("name")})
            return {"label": q["label"], "properties": g.label_properties(q["label"], names)}
        if path == "/api/sodas/values":
            computed = next((c for c in self.store.settings()["computed"]
                             if c.get("label") == q["label"] and c.get("name") == q["property"]), None)
            return {"values": g.property_values(q["label"], q["property"], computed)}
        if path == "/api/sodas/search":
            return g.search(q.get("q", ""), q.get("label") or None, int(q.get("skip", 0)), min(int(q.get("limit", 6)), 200))
        if path == "/api/sodas/node":
            return g.node(q["label"], q["key"])
        raise LookupError("not found")

    # -- POST -----------------------------------------------------------------------------
    def post(self, path: str, body: dict[str, Any]) -> Any:
        g, s = self.graph_now(), self.store.settings()
        per_node = int(s["limits"]["maxPerNode"])
        if path == "/api/sodas/settings":
            return self.store.save_settings(body)
        if path == "/api/sodas/settings/reset":
            return self.store.reset_settings()
        if path == "/api/sodas/sodo-byla":
            out = self.store.import_garden(body.get("file"), body.get("name"))
            self.store.log("info", "sodas", f"įkeltas sodas „{out['name']}“ ({out['nodes']} mazgų)")
            return out
        if path == "/api/vaiva/juodrastis":
            return self.store.save_draft("dirbtuves", body.get("data"))
        if path.startswith("/api/sodas/gardens/"):
            parts = path.removeprefix("/api/sodas/gardens/").split("/")
            if len(parts) == 2 and parts[1] == "duplicate":
                return self.store.duplicate_garden(parts[0], body.get("name"))
            if len(parts) == 2 and parts[1] == "rename":
                return self.store.rename_garden(parts[0], body.get("name", ""))
            if len(parts) == 2 and parts[1] == "delete":
                self.store.delete_garden(parts[0])
                return {"deleted": parts[0]}
            if len(parts) == 1:
                body.pop("_from", None)
                return self.store.save_garden(parts[0], body)
            raise LookupError("not found")
        if path == "/api/sodas/flags":
            from .flags import assign_flags
            r = assign_flags(self.store, self.graph.read)
            self.store.log("info", "sodas", f"vėliavos priskirtos {len(r['added'])} kalbų pavadinimams", "; ".join(r["failed"]) or None)
            return r
        if path == "/api/sodas/log/clear":
            self.store.clear_log()
            return {"cleared": True}
        if path == "/api/sodas/log":
            return self.store.log(body.get("level", "error"), body.get("source", "naršyklė"), body.get("message", ""), body.get("detail"))
        if path.startswith("/api/lkezdb/"):
            return self.lkezdb_post(path.removeprefix("/api/lkezdb/"), body)
        if path == "/api/vaiva/run":
            names = {(n.get("label"), n.get("key")): n.get("display_name") for n in body.get("nodes") or [] if isinstance(n, dict)}
            nodes = [{**r, "display_name": names.get((r["label"], r["key"]))} for r in self.refs(body.get("nodes"))[:200]]
            return self.vaiva.start(str(body["study"]), nodes, body.get("params") or {}, body.get("name"))
        if path.startswith("/api/vaiva/runs/") and path.endswith("/delete"):
            self.vaiva.delete(path.split("/")[-2])
            return {"deleted": True}
        bundle_min = int(s["limits"].get("bundleMin") or 0) or None
        if path == "/api/sodas/expand":
            if body.get("bundle"):   # every node a bundle stands for, from where the bundle stands
                return g.expand(None, None, body.get("mode", "semantic"), min(int(body.get("limit", per_node)), per_node),
                                body.get("types"), source=bundle_source(body["bundle"]), bundle_min=bundle_min)
            return g.expand(body["label"], body["key"], body.get("mode", "semantic"), min(int(body.get("limit", per_node)), per_node),
                            body.get("types"), bundle_min=bundle_min)
        if path == "/api/sodas/page":
            if body.get("bundle"):
                return g.page(None, None, body["type"], bool(body["out"]), int(body.get("skip", 0)), min(int(body.get("take", 20)), per_node),
                              True, source=bundle_source(body["bundle"]), bundle_min=bundle_min)
            return g.page(body["label"], body["key"], body["type"], bool(body["out"]), int(body.get("skip", 0)),
                          min(int(body.get("take", 20)), per_node), bool(body.get("by_name")), bundle_min=bundle_min)
        if path == "/api/sodas/bundle":
            return g.bundle_members(bundle_source(body.get("bundle")), int(body.get("skip", 0)), min(int(body.get("take", 50)), 200))
        if path == "/api/sodas/bundle-map":
            return g.bundle_map(bundle_source(body.get("bundle")), s["map"].get("geoPaths") or [],
                                None if body.get("lexemes") is None else bool(body.get("lexemes")))
        if path == "/api/sodas/node-map":
            way, paths = str(body.get("way") or ""), s["map"].get("geoPaths") or []
            if body.get("bundle"):
                return g.related_map(None, way, paths, bundle=bundle_source(body["bundle"]))
            return g.related_map(self.refs(body.get("nodes")), way, paths)
        if path == "/api/sodas/nodes":
            return {"nodes": g.nodes(self.refs(body.get("nodes")))}
        if path == "/api/sodas/neighbors":
            return g.neighbors(self.refs(body.get("nodes")), body["type"], bool(body.get("out")), body.get("label") or None)
        if path == "/api/sodas/edges-between":
            ids = [str(i) for i in body.get("ids", [])][:1000]
            focus = [str(i) for i in body["focus"]][:1000] if isinstance(body.get("focus"), list) else None
            return {"edges": g.edges_between(ids, body.get("types"), focus)}
        if path == "/api/sodas/label-nodes":
            return g.label_nodes(body["label"], int(body.get("skip", 0)), min(int(body.get("limit", 50)), int(s["limits"]["maxNodes"])))
        if path == "/api/sodas/paths":
            try:
                return g.paths(body["a"], body["b"], body.get("excluded", s["pathExcluded"]))
            except Exception as exc:  # noqa: BLE001 – Neo4j gives up on a search too wide for its time limit
                if "TimedOut" in type(exc).__name__ or "timed out" in str(exc).lower() or "Timeout" in str(getattr(exc, "code", "")):
                    raise ValueError("kelio paieška užtruko per ilgai – pabandykite pridėti bekelių (ryšių, per kuriuos neiti)") from exc
                raise
        if path == "/api/sodas/computed":
            return g.computed(s["computed"], self.refs(body.get("nodes")))
        if path == "/api/sodas/geo":
            return g.geo(s["map"].get("geoPaths") or [], self.refs(body.get("nodes")))
        if path == "/api/sodas/relationship":
            edge = self.rels.create(body["a"], body["b"], body.get("type", ""), body.get("note"))
            self.store.log("info", "sodas", f"sukurtas ryšys {edge['type']}: {body['a']['key']} → {body['b']['key']}")
            return edge
        if path == "/api/sodas/rysiai/istrinti":
            end = body.get("end") if isinstance(body.get("end"), dict) else None
            return self.rels.delete(str(body.get("key") or ""),
                                    {"label": str(end.get("label") or ""), "key": str(end.get("key") or "")} if end else None)
        raise LookupError("not found")

    # -- LKEŽDB ---------------------------------------------------------------------------------
    def lkezdb_get(self, path: str, q: dict[str, str]) -> Any:
        lk = self.lkezdb
        if path == "status":
            from kalba_lkezdb import llm
            if not lk.store.available:
                return {"available": False, "db": str(lk.store.path)}
            return {"available": True, "stats": lk.store.stats(), "db": str(lk.store.path),
                    "engine": llm.public_engine(lk.store), **lk.prompt_list()}
        if path == "words":
            return lk.store.words(q.get("q", ""), q.get("status", ""), int(q.get("offset", 0)), min(200, int(q.get("limit", 50))))
        if path.startswith("word/"):
            return lk.store.word(path.split("/", 1)[1])
        if path == "jobs":
            return {"jobs": lk.store.jobs()}
        if path == "counts":
            return lk.counts()
        if path.startswith("prompt/"):
            return lk.prompt(path.split("/", 1)[1])
        if path.startswith("prompts/"):
            guid, text = lk.prompt_text(path.split("/", 1)[1])
            return {"GUID": guid, "text": text}
        if path == "models":
            from kalba_lkezdb import llm
            return {"models": llm.models(lk.store)}
        raise LookupError("not found")

    def lkezdb_post(self, path: str, body: dict[str, Any]) -> Any:
        lk = self.lkezdb
        words = [str(w) for w in (body.get("words") or ([body["word"]] if body.get("word") else []))][:500]
        if path == "explain":
            return {"jobs": lk.enqueue(words, bool(body.get("include", True)))}
        if path in ("include", "replan"):
            out = {w: getattr(lk, path)(w) for w in words}
            self.store.log("info", "lkezdb", f"{path}: {len(words)} žodž.")
            return out
        if path == "remove":
            out = {w: lk.remove(w) for w in words}
            self.store.log("info", "lkezdb", f"remove: {len(words)} žodž.")
            return out
        if path == "engine":
            from kalba_lkezdb import llm
            return llm.save_engine(lk.store, body)
        if path == "prompts":
            return {"GUID": lk.save_prompt(str(body.get("name") or "užklausa.md"), str(body.get("text") or ""), bool(body.get("activate", True)))}
        if path == "prompts/select":
            lk.select_prompt(str(body["GUID"]))
            return lk.prompt_list()
        if path == "jobs/clear":
            return {"cleared": lk.store.clear_jobs()}
        if path == "delete-all":
            if body.get("confirm") != "IŠTRINTI":
                raise ValueError("Patvirtinkite įrašydami IŠTRINTI.")
            result = lk.delete_all()
            self.store.log("warning", "lkezdb", f"iš Neo4j ištrinti visi LKEŽDB duomenys: {result}")
            return result
        raise LookupError("not found")



GZIP_MIN = 1400          # smaller answers fit one network packet as they are
GZIP_TYPES = ("text/", "application/javascript", "application/json", "image/svg+xml")


def make_app_handler(importer: UIState, app: SodasApp):
    Base = make_handler(importer)
    static_gz: dict[str, bytes] = {}   # ETag → the compressed static file (they change only with a new version)

    class Handler(Base):
        def _gzip_ok(self, body: bytes, content_type: str) -> bool:
            return (len(body) >= GZIP_MIN and content_type.startswith(GZIP_TYPES)
                    and "gzip" in (self.headers.get("Accept-Encoding") or "").lower())

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            """As the importer's, but compressed (JSON of a garden or a neighbourhood: 5–10 times smaller over the
            network; nginx does not compress what it passes on unless told to)."""
            import gzip
            zipped = self._gzip_ok(body, content_type)
            if zipped:
                body = gzip.compress(body, compresslevel=5)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if zipped:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, body: bytes, content_type: str) -> None:
            """A page, script or style: the browser keeps it and only asks whether it changed (ETag → 304), instead of
            loading every script again with every page."""
            import gzip
            import hashlib
            tag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            if tag in (self.headers.get("If-None-Match") or ""):
                self.send_response(304)
                self.send_header("ETag", tag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            zipped = self._gzip_ok(body, content_type)
            if zipped:
                if tag not in static_gz:
                    static_gz[tag] = gzip.compress(body, compresslevel=9)
                body = static_gz[tag]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", tag)
            self.send_header("Vary", "Accept-Encoding")
            if zipped:
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "same-origin")
            super().end_headers()

        def _quietly(self, send, *args) -> None:
            """An answer to a browser that is gone (a closed tab whose long poll ends): nothing to tell, nothing to log."""
            try:
                send(*args)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _fail(self, exc: Exception, where: str) -> None:
            if isinstance(exc, LookupError):
                status = 404
            elif isinstance(exc, (ValueError, KeyError, TypeError)):
                status = 400
            else:
                status = 500
            if status in (400, 500):
                app.store.log("error" if status == 500 else "warning", "serveris", f"{where}: {exc}",
                              traceback.format_exc(limit=4) if status == 500 else None)
            self._json({"error": str(exc)}, status)

        def _same_origin(self) -> bool:
            """Cross-site requests may not change anything (the cookie is SameSite=Lax; this closes the rest)."""
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != (self.headers.get("X-Forwarded-Host") or self.headers.get("Host")):
                return False
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return ctype == "application/json" or bool(self.headers.get("X-Filename"))

        def _dictionary(self, lang: str) -> None:
            """One language's dictionary for i18n.js; the browser keeps it and asks only whether it changed (ETag)."""
            import hashlib
            body = i18n.script(lang).encode("utf-8")
            tag = '"' + hashlib.sha1(body).hexdigest()[:20] + '"'
            if self.headers.get("If-None-Match") == tag:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", J)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", tag)
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, where: str) -> None:
            self.send_response(302)
            self.send_header("Location", where)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            if url.path == "/nustatymai" and q.get("skiltis") in ("duomenynai", "lkezdb"):
                return self._redirect(f"/zeme?skiltis={q['skiltis']}")   # Duomenynai and LKEŽDB moved to Žemė
            if url.path == "/lkezdb" and "embed" not in q:
                rest = urlencode(parse_qs(url.query, keep_blank_values=True), doseq=True)
                return self._redirect("/zeme?skiltis=lkezdb" + (f"&{rest}" if rest else ""))
            if url.path.startswith("/sodas/i18n/") and url.path.endswith(".js"):
                return self._dictionary(url.path.rsplit("/", 1)[-1][:-3])
            if url.path in STATIC:
                name, ctype = STATIC[url.path]
                return self._static(resources.files("kalba_sodas").joinpath("static", *name.split("/")).read_bytes(), ctype)
            if url.path.startswith("/sodas-img/"):
                found = app.store.image(unquote(url.path.rsplit("/", 1)[-1]))
                if not found:
                    return self._json({"error": "not found"}, 404)
                data, ctype = found
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(data)
                return None
            if url.path == "/importas" and "embed" not in q:
                return self._redirect("/zeme")
            if url.path.startswith(("/api/sodas/", "/api/vaiva/", "/api/lkezdb/", "/api/bibliografija", "/api/apie")):
                try:
                    value = app.get(url.path, q)
                except Exception as exc:
                    return self._quietly(self._fail, exc, url.path)
                return self._quietly(self._json, value)
            return super().do_GET()

        def do_POST(self):
            url = urlparse(self.path)
            if not self._same_origin():
                return self._json({"error": "užklausa iš kitos svetainės atmesta"}, 403)
            if int(self.headers.get("Content-Length") or 0) > MAX_BODY:
                return self._json({"error": "užklausa per didelė"}, 413)
            if url.path == "/api/sodas/images":
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > 3 * 1024 * 1024:
                        raise ValueError("paveiksliukas didesnis nei 2 MB")
                    name = unquote(self.headers.get("X-Filename") or "image.png")
                    return self._json({"url": app.store.save_image(name, self.rfile.read(length))})
                except Exception as exc:
                    return self._fail(exc, url.path)
            if url.path.startswith(("/api/sodas/", "/api/vaiva/", "/api/lkezdb/")):
                try:
                    value = app.post(url.path, self._body())
                except Exception as exc:
                    return self._quietly(self._fail, exc, url.path)
                return self._quietly(self._json, value)
            return super().do_POST()

    return Handler


def serve(config: Path, work_dir: Path, neo4j_config: Path, data_dir: Path, host: str = "127.0.0.1", port: int = 8765,
          batch_size: int = 1000, open_browser: bool = True) -> None:
    importer = UIState(config, work_dir, neo4j_config, batch_size)
    store = Store(data_dir)
    app = SodasApp(store, neo4j_config, config)
    server = ThreadingHTTPServer((host, port), make_app_handler(importer, app))
    url = f"http://{host}:{port}/"
    print(f"Sodas: {url}  (žemė: /zeme, sodas: /, Vaiva: /vaiva, nustatymai: /nustatymai; Ctrl+C sustabdo)", flush=True)

    def indexes():
        try:
            n = app.graph.ensure_indexes()
            if n:
                store.log("info", "sodas", f"Neo4j sukurta paieškos indeksų: {n}")
        except Exception:  # noqa: BLE001 – Neo4j not running yet: created at the next start
            pass
    threading.Thread(target=indexes, daemon=True).start()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["SodasApp", "make_app_handler", "serve"]
