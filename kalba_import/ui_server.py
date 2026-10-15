"""Local web UI: choose datasets, preview what they would write, import, resolve, wipe.

Standard library only; binds to 127.0.0.1 by default.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import download as dl
from .import_all import IMPORT_ORDER, read_datasets_config, run_import_all
from .neo4j_admin import neo4j_status, resolve_neo4j, wipe_neo4j
from .neo4j_config import neo4j_settings
from .preview import DatasetPreview, preview_dataset
from .profiles import load_profile_for

WIPE_CONFIRMATION = "IŠTRINTI"
STATIC_FILES = {"/importas": ("index.html", "text/html; charset=utf-8"),
                "/cytoscape.min.js": ("cytoscape.min.js", "application/javascript; charset=utf-8")}


class Job:
    def __init__(self, kind: str, detail: dict[str, Any]):
        self.kind = kind
        self.detail = detail
        self.status = "running"
        self.lines: list[str] = []
        self.result: Any = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: str | None = None

    def log(self, message: str) -> None:
        self.lines.append(f"{datetime.now().strftime('%H:%M:%S')} {message}")
        del self.lines[:-500]

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "detail": self.detail, "status": self.status, "lines": self.lines,
                "result": self.result, "started_at": self.started_at, "finished_at": self.finished_at}


class UIState:
    def __init__(self, config: Path, work_dir: Path, neo4j_config: Path, batch_size: int):
        self.config = config
        self.work_dir = work_dir
        self.neo4j_config = neo4j_config
        self.batch_size = batch_size
        self.job: Job | None = None
        self.lock = threading.Lock()
        self.preview_cache: dict[tuple, dict[str, Any]] = {}
        self.sessions: dict[str, DatasetPreview] = {}
        self._status_cache: tuple[float, dict[str, Any]] | None = None

    # -- helpers -------------------------------------------------------------------
    def settings(self) -> dict[str, str]:
        return neo4j_settings(config_path=self.neo4j_config)

    def neo4j(self, fresh: bool = False) -> dict[str, Any]:
        if not fresh and self._status_cache and time.time() - self._status_cache[0] < 10:
            return self._status_cache[1]
        s = self.settings()
        if not s.get("password"):
            status = {"ok": False, "error": "Neo4j slaptažodis nenurodytas (neo4j.yaml arba KALBA_NEO4J_PASSWORD)"}
        else:
            try:
                status = neo4j_status(s["uri"], s["user"], s["password"], s["database"])
            except Exception as exc:
                status = {"ok": False, "error": str(exc)}
        status.update({"uri": s["uri"], "database": s["database"]})
        self._status_cache = (time.time(), status)
        return status

    def neo4j_datasets(self) -> set[str]:
        st = self.neo4j()
        return {d["dataset"] for d in st.get("datasets", [])} if st.get("ok") else set()

    def datasets(self) -> list[dict[str, Any]]:
        dl.ensure_config(self.config)
        paths = read_datasets_config(self.config)
        log_path = self.work_dir / "import-all-log.json"
        last = {}
        if log_path.exists():
            try:
                last = {d["dataset_id"]: d.get("status") for d in json.loads(log_path.read_text(encoding="utf-8")).get("datasets", [])}
            except Exception:
                last = {}
        in_db = self.neo4j_datasets()
        out = []
        for position, dataset_id in enumerate(IMPORT_ORDER, start=1):
            profile = load_profile_for(dataset_id)
            path = paths.get(dataset_id)
            out.append({
                "id": dataset_id, "order": position, "title": profile.raw.get("title") or dataset_id,
                "path": str(path) if path else None, "exists": bool(path and path.exists()),
                "verified": profile.verified, "authorities": profile.authorities,
                "intent": profile.semantics.get("table_intent"), "in_neo4j": dataset_id in in_db,
                "last_import": last.get(dataset_id),
                "download": self._download_info(dataset_id, path),
            })
        return out

    @staticmethod
    def _download_info(dataset_id: str, path: Path | None) -> dict[str, Any] | None:
        src = dl.CATALOG.get(dataset_id)
        if src is None:
            return None
        have = dl.installed(path) if path and path.exists() else None
        return {"version": src.version, "license": src.license, "size_mb": src.size_mb, "page": src.page, "repo": src.repo,
                "installed": have.get("version") if have else None}

    def start_job(self, kind: str, detail: dict[str, Any], work: Callable[[Job], Any]) -> Job:
        with self.lock:
            if self.job and self.job.status == "running":
                raise RuntimeError(f"jau vykdoma: {self.job.kind}")
            job = Job(kind, detail)
            self.job = job

        def runner():
            try:
                job.result = work(job)
                job.status = "ok" if not isinstance(job.result, dict) or job.result.get("status") in (None, "ok", "completed") else "failed"
            except Exception as exc:
                job.status = "failed"
                job.result = {"error": str(exc)}
                job.log("KLAIDA: " + str(exc))
                job.log(traceback.format_exc(limit=3))
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat()
                self._status_cache = None
                self.preview_cache.clear()
        threading.Thread(target=runner, daemon=True).start()
        return job

    # -- actions -------------------------------------------------------------------
    def session(self, dataset: str) -> DatasetPreview:
        if dataset not in self.sessions:
            path = read_datasets_config(self.config).get(dataset)
            if path is None or not path.exists():
                raise FileNotFoundError(f"{dataset}: kelias nerastas {self.config}")
            self.sessions[dataset] = DatasetPreview(dataset, path, load_profile_for(dataset))
        return self.sessions[dataset]

    def preview(self, dataset: str, sample: int, filter_text: str, selected: set[str]) -> dict[str, Any]:
        key = (dataset, sample, filter_text)
        if key not in self.preview_cache:
            session = self.session(dataset)
            self.preview_cache[key] = preview_dataset(dataset, session.ins.path, session.profile, sample=sample,
                                                      filter_text=filter_text, session=session)
        result = dict(self.preview_cache[key])
        in_db = self.neo4j_datasets()
        result["dependencies"] = [{**d, "in_neo4j": d["authority"] in in_db, "selected": d["authority"] in selected}
                                  for d in result["dependencies"]]
        return result

    def start_import(self, datasets: list[str], force: bool = False) -> Job:
        if not datasets:
            raise ValueError("nepasirinktas nė vienas duomenynas")

        def work(job: Job):
            return run_import_all(self.config, self.work_dir, batch_size=self.batch_size, neo4j_config=self.neo4j_config,
                                  progress=job.log, only=datasets, force=force)
        return self.start_job("import", {"datasets": datasets, "force": force}, work)

    def start_download(self, datasets: list[str], replace: bool = False) -> Job:
        if not datasets:
            raise ValueError("nepasirinktas nė vienas duomenynas")
        unknown = [d for d in datasets if d not in dl.CATALOG]
        if unknown:
            raise ValueError(f"nežinomi duomenynai: {', '.join(unknown)}")

        def work(job: Job):
            out = dl.download_many(datasets, self.config, progress=job.log, replace=replace)
            self.sessions.clear()
            return out
        return self.start_job("download", {"datasets": datasets, "replace": replace}, work)

    def start_resolve(self) -> Job:
        s = self.settings()
        return self.start_job("resolve", {}, lambda job: resolve_neo4j(s["uri"], s["user"], s["password"], s["database"], progress=job.log))

    def start_wipe(self, confirmation: str, include_lookup: bool) -> Job:
        if confirmation.strip() != WIPE_CONFIRMATION:
            raise ValueError(f"patvirtinimui įveskite {WIPE_CONFIRMATION}")
        s = self.settings()
        return self.start_job("wipe", {"include_lookup_indexes": include_lookup},
                              lambda job: wipe_neo4j(s["uri"], s["user"], s["password"], s["database"],
                                                     include_lookup_indexes=include_lookup, progress=job.log))


def make_handler(state: UIState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep terminal quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value: Any, status: int = 200) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in STATIC_FILES:
                    name, ctype = STATIC_FILES[url.path]
                    data = resources.files("kalba_import").joinpath("ui", name).read_bytes()
                    return self._send(200, data, ctype)
                if url.path == "/api/state":
                    return self._json({"datasets": state.datasets(), "neo4j": state.neo4j(fresh=q.get("fresh") == "1"),
                                       "job": state.job.as_dict() if state.job else None,
                                       "wipe_confirmation": WIPE_CONFIRMATION})
                if url.path == "/api/job":
                    return self._json(state.job.as_dict() if state.job else None)
                if url.path == "/api/expand":
                    limit = max(1, min(int(q.get("limit", 150)), 1000))
                    return self._json(state.session(q["dataset"]).expand(q["key"], limit=limit))
                if url.path == "/api/preview":
                    selected = {s for s in q.get("selected", "").split(",") if s}
                    sample = max(1, min(int(q.get("n", 25)), 500))
                    return self._json(state.preview(q["dataset"], sample, q.get("filter", ""), selected))
                return self._json({"error": "not found"}, 404)
            except Exception as exc:
                return self._json({"error": str(exc)}, 500)

        def do_POST(self):
            url = urlparse(self.path)
            try:
                body = self._body()
                if url.path == "/api/import":
                    return self._json(state.start_import(list(body.get("datasets", [])), bool(body.get("force"))).as_dict())
                if url.path == "/api/download":
                    return self._json(state.start_download(list(body.get("datasets", [])), bool(body.get("replace"))).as_dict())
                if url.path == "/api/resolve":
                    return self._json(state.start_resolve().as_dict())
                if url.path == "/api/wipe":
                    return self._json(state.start_wipe(str(body.get("confirmation", "")), bool(body.get("include_lookup_indexes"))).as_dict())
                return self._json({"error": "not found"}, 404)
            except (ValueError, RuntimeError) as exc:
                return self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except Exception as exc:
                return self._json({"error": str(exc)}, 500)
    return Handler
