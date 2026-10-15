"""Read-mostly Neo4j access for the research garden.

Every label / relationship type that reaches a query string is checked against ``NAME``;
all values are parameters.  Reads run in read transactions with a timeout, so a user-edited
computed-property pattern can never write.

``Graph.scoped(datasets, blocked)`` is the same graph seen through some datasets only (or without the datasets switched
off, ⚙ → Duomenynai): every node a query returns must belong to one of them (``dataset``, else the authority or the
key's prefix).
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from kalba_import.util import normalize_ascii, normalize_search_text

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
REL_TYPE_NEW = re.compile(r"^[A-Z][A-Z0-9_]{0,47}$")
# relationships drawn in the garden (Ctrl+J) belong to this dataset
ADDITIONS = "Papildymai"
TECHNICAL_LABELS = {"SourceRecord", "SourceTable", "DatasetRelease", "Dataset", "ImportRun", "RawReference"}
REGISTRY_TYPES = {"IN_TABLE", "IN_RELEASE", "RELEASE_OF", "IMPORTS", "REFERS_TO_RECORD", "FROM_RECORD", "DERIVED_FROM"}
# "Rodyk svarbiausia": lexical, semantic, genealogical and borrowing relations only.
CORE_TYPES = {"USED_IN", "HAS_FORM", "HAS_SENSE", "DENOTES", "COGNATE_IN", "RECONSTRUCTED_FOR", "BORROWED_FROM",
              "HAS_BORROWING", "CORRESPONDS_TO", "PARENT_OF", "CONCEPT_RELATION", "ASSOCIATED_WITH", "COLEXIFIES"}
HIDDEN_PROPS = re.compile(r"^(search_|normalization_)")
FORBIDDEN_PATTERN = re.compile(r"\b(CALL|CREATE|MERGE|DELETE|DETACH|SET|REMOVE|LOAD|FOREACH|UNWIND|WITH|RETURN|MATCH|"
                               r"WHERE|USE|UNION|OPTIONAL|ORDER|LIMIT|SKIP)\b|;|//|/\*|`", re.IGNORECASE)
READ_TIMEOUT = 30
SCHEMA_TTL = 30          # seconds the label and type lists are reused (every search and node asks for them)
SEARCH_THREADS = 8       # labels searched at the same time


def check_name(name: Any, what: str = "vardas") -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(f"netinkamas {what}: {name!r}")
    return name


def check_pattern(pattern: str) -> str:
    """A computed-property path: one pattern from ``(n...)`` to a node bound as ``t``."""
    p = (pattern or "").strip()
    if not p.startswith(("(n)", "(n:")) or not re.search(r"\(t[:)\s]", p) or FORBIDDEN_PATTERN.search(p) or len(p) > 300:
        raise ValueError("šablonas turi prasidėti (n) arba (n:Etiketė), turėti tikslą (t) ir būti vien kelio aprašas")
    for label in re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", p):
        check_name(label, "etiketė")
    return p


def check_rel_type(rel_type: Any) -> str:
    if not isinstance(rel_type, str) or not REL_TYPE_NEW.match(rel_type):
        raise ValueError("ryšio tipas: didžiosios raidės, skaičiai ir _, pvz. SIMILAR_TO")
    return rel_type


def node_id(label: str, key: str) -> str:
    return f"{label}|{key}"


def _clean_props(props: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in props.items() if not HIDDEN_PROPS.match(k)}


def node_out(node: Any, degree: int | None = None) -> dict[str, Any]:
    labels = sorted(node.labels)
    label = labels[0] if labels else "Node"
    props = dict(node)
    key = props.get("key") or node.element_id
    return {"id": node_id(label, key), "label": label, "key": key, "display_name": props.get("display_name") or props.get("name")
            or props.get("value") or key, "dataset": props.get("dataset"), "degree": degree, "props": _clean_props(props)}


# a relationship with just the ids of its ends (``_ref``), not their whole nodes
ENDS = ("WITH r, startNode(r) AS s, endNode(r) AS e "
        "RETURN r, labels(s) AS sl, coalesce(s.key, elementId(s)) AS sk, labels(e) AS el, coalesce(e.key, elementId(e)) AS ek")


def _ref(labels: list[str], key: str) -> dict[str, Any]:
    """Just the id of a node (as ``node_out`` makes it), where only a relationship's end is needed."""
    labels = sorted(labels)
    return {"id": node_id(labels[0] if labels else "Node", key)}


def rel_out(rel: Any, start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
    props = dict(rel)
    return {"id": "r|" + (props.get("key") or rel.element_id), "type": rel.type, "source": start["id"], "target": end["id"],
            "props": _clean_props(props)}


class _Connection:
    """One Neo4j driver shared by a graph and its scoped views (and the schema they last read, for SCHEMA_TTL)."""

    def __init__(self, settings_func):
        self.settings_func = settings_func
        self.driver = None
        self.ident: tuple | None = None
        self.lock = threading.Lock()
        self.schema: tuple[float, dict[str, Any]] | None = None

    def get(self):
        s = self.settings_func()
        ident = (s["uri"], s["user"], s["password"])
        with self.lock:
            if self.driver is None or self.ident != ident:
                from neo4j import GraphDatabase
                if self.driver is not None:
                    self.driver.close()
                self.driver = GraphDatabase.driver(s["uri"], auth=(s["user"], s["password"]), notifications_min_severity="OFF")
                self.ident = ident
                self.schema = None
            return self.driver, s["database"]


class Graph:
    def __init__(self, settings_func, allowed: list[str] | None = None, _conn: _Connection | None = None,
                 blocked: list[str] | None = None):
        self._conn = _conn or _Connection(settings_func)
        self.allowed = sorted(set(allowed)) if allowed is not None else None
        self.blocked = sorted(set(blocked)) if blocked else None

    def scoped(self, allowed: list[str] | None, blocked: list[str] | None = None) -> "Graph":
        """This graph limited to ``allowed`` datasets (``None``: all of them) without the ``blocked`` ones (datasets
        switched off: ⚙ → Duomenynai)."""
        return self if allowed is None and not blocked else Graph(None, allowed, self._conn, blocked)

    @property
    def whole(self) -> bool:
        """Every dataset is seen (no condition on the nodes a query returns)."""
        return self.allowed is None and self.blocked is None

    def _params(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.allowed is not None:
            out["allowed_ds"] = self.allowed
        if self.blocked is not None:
            out["blocked_ds"] = self.blocked
        return out

    def ok(self, var: str) -> str:
        """A Cypher condition: node ``var`` belongs to an allowed dataset ("true" when not scoped)."""
        if self.whole:
            return "true"
        ds = f"coalesce({var}.dataset, {var}.authority, split(split({var}.key, '@')[0], ':')[0])"
        parts = ([f"{ds} IN $allowed_ds"] if self.allowed is not None else []) + \
            ([f"NOT coalesce({ds} IN $blocked_ds, false)"] if self.blocked is not None else [])
        return "(" + " AND ".join(parts) + ")"

    def _and(self, var: str) -> str:
        return "" if self.whole else f" AND {self.ok(var)}"

    def _where(self, var: str) -> str:
        return "" if self.whole else f" WHERE {self.ok(var)}"

    # -- connection ---------------------------------------------------------------------
    def driver(self):
        return self._conn.get()

    def read(self, query: str, **params) -> list[Any]:
        from neo4j import unit_of_work
        driver, database = self.driver()
        for k, v in self._params().items():
            params.setdefault(k, v)

        @unit_of_work(timeout=READ_TIMEOUT)
        def work(tx):
            return list(tx.run(query, **params))
        with driver.session(database=database) as session:
            return session.execute_read(work)

    def read_many(self, queries: list[str | tuple[str, dict[str, Any]]]) -> list[list[Any]]:
        """Several small reads in one transaction (count-store lookups for the type list); a query, or (query, params)."""
        from neo4j import unit_of_work
        driver, database = self.driver()
        scope = self._params()

        @unit_of_work(timeout=READ_TIMEOUT)
        def work(tx):
            return [list(tx.run(q, **scope)) if isinstance(q, str) else list(tx.run(q[0], **{**scope, **q[1]})) for q in queries]
        with driver.session(database=database) as session:
            return session.execute_read(work)

    def status(self) -> dict[str, Any]:
        if not self._conn.settings_func().get("password"):
            return {"ok": False, "error": "Neo4j slaptažodis nenurodytas (neo4j.yaml arba KALBA_NEO4J_PASSWORD)"}
        try:
            rows = self.read("MATCH (d:Dataset) RETURN d.key AS k ORDER BY k")
            return {"ok": True, "datasets": [r["k"] for r in rows]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def schema(self) -> dict[str, Any]:
        cached = self._conn.schema
        if cached and time.monotonic() - cached[0] < SCHEMA_TTL:
            return {k: list(v) if isinstance(v, list) else v for k, v in cached[1].items()}
        labels, types = self.read_many(["CALL db.labels() YIELD label RETURN label ORDER BY label",
                                        "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType"])
        out = {"labels": [r["label"] for r in labels], "types": [r["relationshipType"] for r in types],
               "technical_labels": sorted(TECHNICAL_LABELS), "registry_types": sorted(REGISTRY_TYPES), "core_types": sorted(CORE_TYPES)}
        self._conn.schema = (time.monotonic(), out)
        return {k: list(v) if isinstance(v, list) else v for k, v in out.items()}

    def forget_schema(self) -> None:
        """A new relationship type (Ctrl+J) is listed at once, not after SCHEMA_TTL."""
        self._conn.schema = None

    def ensure_indexes(self) -> int:
        """Indexes the program looks nodes up by (kalba_import.cypher.LOOKUP_INDEXES) – also in a database imported before
        they were part of the schema. ``IF NOT EXISTS``: once they are there, nothing is done."""
        from kalba_import.cypher import lookup_index_cypher
        driver, database = self.driver()
        with driver.session(database=database) as session:
            have = {r["name"] for r in session.run("SHOW INDEXES YIELD name RETURN name")}
            todo = [q for q in lookup_index_cypher() if q.split()[3] not in have]
            for q in todo:
                try:
                    session.run(q).consume()
                except Exception:  # noqa: BLE001 – the same index under another name: nothing to add
                    pass
        return len(todo)

    # -- type list ------------------------------------------------------------------------
    def label_counts(self) -> list[dict[str, Any]]:
        labels = self.schema()["labels"]
        rows = self.read_many([f"MATCH (n:`{check_name(l, 'etiketė')}`) RETURN count(n) AS c" for l in labels])
        return [{"label": l, "count": r[0]["c"], "technical": l in TECHNICAL_LABELS} for l, r in zip(labels, rows) if r[0]["c"]]

    def label_rel_types(self, label: str) -> list[dict[str, Any]]:
        """Relationship types of a label with exact out/in counts from Neo4j's count store (no scan)."""
        label = check_name(label, "etiketė")
        types = self.schema()["types"]
        queries = []
        for t in types:
            queries.append(f"MATCH (:`{label}`)-[r:`{check_name(t, 'ryšio tipas')}`]->() RETURN count(r) AS c")
            queries.append(f"MATCH (:`{label}`)<-[r:`{t}`]-() RETURN count(r) AS c")
        rows = self.read_many(queries)
        out = []
        for i, t in enumerate(types):
            o, n = rows[2 * i][0]["c"], rows[2 * i + 1][0]["c"]
            if o or n:
                out.append({"type": t, "out": o, "in": n})
        return out

    def label_nodes(self, label: str, skip: int = 0, limit: int = 50) -> dict[str, Any]:
        label = check_name(label, "etiketė")
        rows = self.read(f"MATCH (n:`{label}`) WITH n SKIP $skip LIMIT $limit RETURN n, COUNT {{ (n)--() }} AS deg",
                         skip=int(skip), limit=int(limit))
        total = self.read(f"MATCH (n:`{label}`) RETURN count(n) AS c")[0]["c"]
        return {"nodes": [node_out(r["n"], r["deg"]) for r in rows], "total": total}

    def label_properties(self, label: str, computed_names: list[str]) -> list[dict[str, Any]]:
        """Property names seen on (a sample of) this label, plus computed properties defined for it."""
        label = check_name(label, "etiketė")
        rows = self.read(f"MATCH (n:`{label}`) WITH n LIMIT 2000 UNWIND keys(n) AS k RETURN k, count(*) AS c ORDER BY k")
        props = [{"name": r["k"], "count": r["c"], "computed": False} for r in rows if not HIDDEN_PROPS.match(r["k"])]
        props.insert(0, {"name": "display_name", "count": None, "computed": False}) if not any(p["name"] == "display_name" for p in props) else None
        return [*({"name": n, "count": None, "computed": True} for n in computed_names), *props]

    def property_values(self, label: str, prop: str, computed: dict[str, Any] | None = None, limit: int = 300) -> list[dict[str, Any]]:
        """Most frequent values of a (stored or computed) property on this label."""
        label = check_name(label, "etiketė")
        if computed:
            pattern = check_pattern(computed["pattern"])
            rows = self.read(f"MATCH (n:`{label}`){self._where('n')} WITH n LIMIT 5000 MATCH {pattern}{self._where('t')} "
                             "WITH coalesce(t.display_name, t.name, t.key) AS v RETURN v, count(*) AS c ORDER BY c DESC LIMIT $limit",
                             limit=int(limit))
        else:
            rows = self.read(f"MATCH (n:`{label}`) WHERE n[$p] IS NOT NULL{self._and('n')} WITH n[$p] AS v LIMIT 20000 "
                             "UNWIND (CASE WHEN v IS :: LIST<ANY> THEN v ELSE [v] END) AS x "
                             "RETURN toString(x) AS v, count(*) AS c ORDER BY c DESC LIMIT $limit", p=prop, limit=int(limit))
        return [{"value": r["v"], "count": r["c"]} for r in rows if r["v"] not in (None, "")]

    # -- search ---------------------------------------------------------------------------
    def search(self, q: str, label: str | None = None, skip: int = 0, limit: int = 6) -> dict[str, Any]:
        raw = (q or "").strip()
        if len(raw) < 1:
            return {"q": raw, "groups": [], "types": []}
        qn, qa = normalize_search_text(raw) or "", normalize_ascii(raw) or ""
        schema = self.schema()
        labels = [check_name(label, "etiketė")] if label else [l for l in schema["labels"] if l not in TECHNICAL_LABELS]

        # Best matches first: the same text, then the same text without accents and marks ("mesti" finds "mèsti" as
        # well as "mesti"), then longer names starting with it (the exact name, shorter names first). Among the exact
        # matches the names take turns (each name once, then each a second time, …), so one name repeated in many
        # datasets does not fill the first page. Sorted and cut in Neo4j, so only the page travels, not up to 1001
        # rows of every label. Labels are searched side by side.
        def one(lab: str) -> dict[str, Any] | None:
            rows = self.read(
                f"MATCH (n:`{lab}`) WHERE (n.search_text STARTS WITH $qn OR n.search_ascii STARTS WITH $qa "
                f"OR n.display_name STARTS WITH $raw){self._and('n')} WITH n LIMIT 1001 "
                "WITH n, CASE WHEN n.display_name IS NULL OR n.display_name = '' THEN n.key ELSE toString(n.display_name) END AS dn "
                "WITH n, dn, CASE WHEN coalesce(n.search_text, '') = $qn THEN 0 WHEN coalesce(n.search_ascii, '') = $qa THEN 1 ELSE 2 END AS r "
                "ORDER BY n.dataset, n.key "
                "WITH r, dn, collect({key: n.key, name: dn, dataset: n.dataset}) AS same "
                "ORDER BY r, dn <> $raw, size(dn), dn "
                "WITH collect({r: r, same: same}) AS names "
                "UNWIND range(0, size(names) - 1) AS g UNWIND range(0, size(names[g].same) - 1) AS i "
                "WITH names[g].same[i] AS hit, g, CASE WHEN names[g].r < 2 THEN i ELSE 0 END AS turn, names[g].r < 2 AS exact "
                "ORDER BY exact DESC, turn, g, i "
                "WITH collect(hit) AS hits "
                "RETURN size(hits) AS total, hits[$skip..$end] AS items",
                qn=qn, qa=qa or qn, raw=raw, skip=int(skip), end=int(skip) + int(limit))
            total = rows[0]["total"] if rows else 0
            if not total:
                return None
            items = [{"id": node_id(lab, r["key"]), "label": lab, "key": r["key"], "display_name": r["name"], "dataset": r["dataset"]}
                     for r in rows[0]["items"]]
            return {"label": lab, "total": total, "more": total > 1000, "items": items}
        if len(labels) == 1:
            found = [one(labels[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(SEARCH_THREADS, len(labels))) as pool:
                found = list(pool.map(one, labels))
        groups = [g for g in found if g]
        groups.sort(key=lambda g: (-sum(1 for i in g["items"] if normalize_search_text(i["display_name"]) == qn
                                       or (qa and normalize_ascii(i["display_name"]) == qa)), -g["total"]))
        types = []
        if not label and self.whole:
            needle = raw.casefold()
            matching = [t for t in schema["types"] if needle in t.casefold()]
            if matching:
                counts = self.read_many([f"MATCH ()-[r:`{check_name(t, 'ryšio tipas')}`]->() RETURN count(r) AS c" for t in matching])
                types = [{"type": t, "count": c[0]["c"]} for t, c in zip(matching, counts)]
        return {"q": raw, "groups": groups, "types": types}

    # -- nodes & neighbourhood ------------------------------------------------------------
    def node(self, label: str, key: str) -> dict[str, Any]:
        label = check_name(label, "etiketė")
        if self.whole:
            # Neo4j keeps every node's degree per type and direction: read, not counted (a source table: 4 s → 2 ms)
            types = [check_name(t, "ryšio tipas") for t in self.schema()["types"]]
            degrees = ", ".join(f"COUNT {{ (n)-[:`{t}`]->() }}, COUNT {{ (n)<-[:`{t}`]-() }}" for t in types)
            rows = self.read(f"MATCH (n:`{label}` {{key: $key}}) RETURN n, [{degrees}] AS d", key=key)
            if rows:
                d = rows[0]["d"]
                rows[0] = {"n": rows[0]["n"], "counts": [{"type": t, "out": out, "count": d[2 * i + (0 if out else 1)]}
                                                         for i, t in enumerate(types) for out in (True, False) if d[2 * i + (0 if out else 1)]]}
        else:
            rows = self.read(
                f"MATCH (n:`{label}` {{key: $key}}){self._where('n')} "
                f"CALL (n) {{ MATCH (n)-[r]-(m) WHERE {self.ok('m')} RETURN type(r) AS t, startNode(r) = n AS out, count(*) AS c }} "
                "RETURN n, collect({type: t, out: out, count: c}) AS counts", key=key)
        if not rows:
            raise LookupError(f"mazgas nerastas: {label} {key}")
        counts = sorted(rows[0]["counts"], key=lambda c: (-c["count"], c["type"]))
        out = node_out(rows[0]["n"], sum(c["count"] for c in counts))
        out["relationship_counts"] = counts
        src = out["props"].get("source_record_key")
        if src:
            rec = self.read(f"MATCH (s:SourceRecord {{key: $k}}){self._where('s')} RETURN s.raw_json AS raw", k=src)
            out["source_record"] = rec[0]["raw"] if rec else None
        return out

    def _groups(self, counts: list[dict[str, Any]], mode: str, types: list[str] | None) -> list[dict[str, Any]]:
        wanted = []
        for c in counts:
            t = c["type"]
            if types is not None and t not in types:
                continue
            if mode == "core" and t not in CORE_TYPES:
                continue
            if mode == "semantic" and t in REGISTRY_TYPES:
                continue
            wanted.append(c)
        return wanted

    # Neighbours of one type with the same name are drawn as one merged node ("rain ×125") in the garden, so the
    # budget of an expansion counts names, not relationships: all relationships of a name come together (pages
    # are ordered by name). A name with more than ``REL_CAP_PER_NAME`` relationships comes as one *bundle* node
    # ("skin ×10963"): its members are not sent at all, yet the garden shows how many there are; the bundle can be
    # expanded, listed and shown on the map by the server (``source`` below).
    REL_CAP_PER_NAME = 20     # a name with more relationships is a bundle (unless the settings say otherwise)
    MAX_PLAIN_NAME = 1000     # … and above this always
    BUNDLE_DEPTH = 3          # a bundle of a bundle of a bundle …
    MAP_POINTS = 50000        # most points a bundle's map sends

    # A *source* is what is expanded: a node {"label", "key"} or a bundle {"bundle": {"source", "type", "out", "name",
    # "label"}} – the ``label`` nodes named ``name`` reached from ``source`` over ``type`` (``out``: source → them).
    @staticmethod
    def source_id(src: dict[str, Any]) -> str:
        if "bundle" in src:
            b = src["bundle"]
            return f"bundle|{Graph.source_id(b['source'])}|{b['type']}|{'out' if b['out'] else 'in'}|{b['name']}"
        return node_id(src["label"], src["key"])

    def _source(self, src: dict[str, Any], var: str = "n", depth: int = 0) -> tuple[str, dict[str, Any]]:
        """Cypher binding ``var`` to the source's node(s) (a bundle: each of its members once), with its parameters."""
        if not isinstance(src, dict):
            raise ValueError("netinkamas šaltinis")
        if "bundle" not in src:
            return f"MATCH ({var}:`{check_name(src.get('label'), 'etiketė')}` {{key: $k{depth}}})", {f"k{depth}": str(src.get("key") or "")}
        if depth >= self.BUNDLE_DEPTH:
            raise ValueError("per gilus pluoštas")
        b = src["bundle"]
        inner = f"s{depth}"
        q, params = self._source(b.get("source"), inner, depth + 1)
        t, lab = check_name(b.get("type"), "ryšio tipas"), check_name(b.get("label"), "etiketė")
        pat = f"({inner})-[:`{t}`]->({var}:`{lab}`)" if b.get("out") else f"({inner})<-[:`{t}`]-({var}:`{lab}`)"
        q += f" MATCH {pat} WHERE coalesce({var}.display_name, {var}.key) = $n{depth}{self._and(var)} WITH DISTINCT {var}"
        return q, {**params, f"n{depth}": str(b.get("name"))}

    @staticmethod
    def _bundle_back(src: dict[str, Any]) -> tuple[str, bool] | None:
        """The (type, direction) leading from a bundle's members back to its source: the bundle's own edge stands for it."""
        if "bundle" not in src:
            return None
        return src["bundle"]["type"], not bool(src["bundle"]["out"])

    def bundle_counts(self, src: dict[str, Any]) -> list[dict[str, Any]]:
        """Relationship counts of a bundle's members by type and direction (as ``node``'s ``relationship_counts``)."""
        q, params = self._source(src)
        rows = self.read(f"{q} MATCH (n)-[r]-(m) WHERE {self.ok('m')} RETURN type(r) AS t, startNode(r) = n AS out, count(*) AS c",
                         **params)
        back = self._bundle_back(src)
        counts = [{"type": r["t"], "out": r["out"], "count": r["c"]} for r in rows if (r["t"], r["out"]) != back]
        return sorted(counts, key=lambda c: (-c["count"], c["type"]))

    def _name_runs(self, src: dict[str, Any], rel_type: str, out: bool) -> list[dict[str, Any]]:
        """Neighbour names in page order: how many relationships each, of which label(s) and dataset."""
        q, params = self._source(src)
        pattern = f"(n)-[r:`{rel_type}`]->(m)" if out else f"(n)<-[r:`{rel_type}`]-(m)"
        rows = self.read(
            f"{q} MATCH {pattern}{self._where('m')} "
            "WITH coalesce(m.display_name, m.key) AS name, count(*) AS c, collect(DISTINCT head(labels(m)))[..2] AS labs, "
            "head(collect(m.dataset)) AS ds ORDER BY name RETURN name, c, labs, ds", **params)
        return [{"name": r["name"], "count": r["c"], "labels": r["labs"], "dataset": r["ds"]} for r in rows]

    @classmethod
    def _take(cls, runs: list[dict[str, Any]], skip: int, names: int) -> tuple[list[dict[str, Any]], int]:
        """Up to ``names`` whole names from relationship offset ``skip`` on (a name cut by ``skip`` is taken whole);
        returns them and the offset after the last one."""
        pos, taken = 0, []
        for run in runs:
            end = pos + run["count"]
            if end > skip and len(taken) < names:
                taken.append(run)
            elif len(taken) >= names:
                break
            pos = end
        return taken, (pos if taken else skip)

    def _bundle(self, src: dict[str, Any], rel_type: str, out: bool, run: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """The node standing for all ``run`` neighbours of one name, and its edge to the source."""
        desc = {"source": src, "type": rel_type, "out": bool(out), "name": run["name"], "label": run["labels"][0]}
        sid = self.source_id(src)
        bid = self.source_id({"bundle": desc})
        node = {"id": bid, "label": desc["label"], "key": "", "display_name": run["name"], "dataset": run.get("dataset"),
                "degree": run["count"], "props": {}, "kind": "bundle", "count": run["count"], "bundle": desc, "center": sid}
        edge = {"id": f"{bid}|e", "type": rel_type, "source": sid if out else bid, "target": bid if out else sid,
                "props": {"count": run["count"]}}
        return node, edge

    def _fetch(self, src: dict[str, Any], rel_type: str, out: bool, names: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The neighbours of these names with their relationships (from a bundle: one edge per neighbour, with a count)."""
        if not names:
            return [], []
        q, params = self._source(src)
        pattern = f"(n)-[r:`{rel_type}`]->(m)" if out else f"(n)<-[r:`{rel_type}`]-(m)"
        where = f" WHERE coalesce(m.display_name, m.key) IN $names{self._and('m')}"
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        if "bundle" not in src:
            rows = self.read(f"{q} MATCH {pattern}{where} RETURN labels(n) AS nl, r, m, COUNT {{ (m)--() }} AS deg",
                             names=names, **params)
            for row in rows:   # the centre's whole node is not sent with each row: its id is enough
                n, m = _ref(row["nl"], src["key"]), node_out(row["m"], row["deg"])
                nodes[m["id"]] = m
                edges.append(rel_out(row["r"], n if out else m, m if out else n))
            return list(nodes.values()), edges
        sid = self.source_id(src)
        rows = self.read(f"{q} MATCH {pattern}{where} WITH m, count(r) AS c RETURN m, c, COUNT {{ (m)--() }} AS deg",
                         names=names, **params)
        for row in rows:
            m = node_out(row["m"], row["deg"])
            nodes[m["id"]] = m
            edges.append({"id": f"bx|{sid}|{rel_type}|{'out' if out else 'in'}|{m['id']}", "type": rel_type,
                          "source": sid if out else m["id"], "target": m["id"] if out else sid, "props": {"count": row["c"]}})
        return list(nodes.values()), edges

    def _names_page(self, src: dict[str, Any], rel_type: str, out: bool, runs: list[dict[str, Any]], skip: int,
                    names: int, bundle_min: int | None = None) -> dict[str, Any]:
        """``names`` neighbour names from offset ``skip``: big ones (``bundle_min`` relationships or more) as bundles,
        the others node by node."""
        taken, end = self._take(runs, skip, names)
        least = max(2, int(bundle_min or self.REL_CAP_PER_NAME + 1))
        nodes, edges, plain = [], [], []
        for run in taken:
            if (run["count"] >= least or run["count"] > self.MAX_PLAIN_NAME) and len(run["labels"]) == 1:
                b, e = self._bundle(src, rel_type, out, run)
                nodes.append(b)
                edges.append(e)
            else:
                plain.append(run["name"])
        more_nodes, more_edges = self._fetch(src, rel_type, out, plain)
        return {"nodes": nodes + more_nodes, "edges": edges + more_edges, "next": end}

    def expand(self, label: str | None, key: str | None, mode: str = "semantic", limit: int = 50,
               types: list[str] | None = None, source: dict[str, Any] | None = None, bundle_min: int | None = None) -> dict[str, Any]:
        """Neighbourhood with at most ``limit`` neighbour names (see ``_name_runs``); the rest is reported per type as ``more``.
        ``source``: a bundle (or a node) instead of ``label`` / ``key``."""
        src = source or {"label": check_name(label, "etiketė"), "key": key}
        if "bundle" in src:
            info = None
            counts = self.bundle_counts(src)
        else:
            info = self.node(src["label"], src["key"])
            counts = info["relationship_counts"]
        groups = [{**g, "runs": self._name_runs(src, check_name(g["type"], "ryšio tipas"), g["out"])}
                  for g in self._groups(counts, mode, types)]
        # Share the budget: small groups are shown whole, large ones get an equal slice of what remains.
        groups.sort(key=lambda g: len(g["runs"]))
        budget = max(0, int(limit))
        nodes: dict[str, dict[str, Any]] = {info["id"]: {k: v for k, v in info.items() if k != "relationship_counts"}} if info else {}
        edges: list[dict[str, Any]] = []
        more = []
        for i, g in enumerate(groups):
            share = budget // max(1, len(groups) - i) if budget else 0
            shown = 0
            if share:
                part = self._names_page(src, g["type"], g["out"], g["runs"], 0, share, bundle_min)
                budget -= min(share, len(g["runs"]))
                shown = part["next"]
                nodes.update({n["id"]: n for n in part["nodes"]})
                edges.extend(part["edges"])
            if g["count"] > shown:
                more.append({"type": g["type"], "out": g["out"], "total": g["count"], "shown": shown})
        if info and mode == "all" and info["props"].get("source_record_key"):
            rec = self.read(f"MATCH (s:SourceRecord {{key: $k}}){self._where('s')} RETURN s, COUNT {{ (s)--() }} AS deg",
                            k=info["props"]["source_record_key"])
            if rec:
                s = node_out(rec[0]["s"], rec[0]["deg"])
                nodes[s["id"]] = s
                edges.append({"id": f"src|{info['id']}", "type": "source_record_key", "source": info["id"], "target": s["id"],
                              "props": {"virtual": True}})
        return {"center": self.source_id(src), "nodes": list(nodes.values()), "edges": edges, "more": more}

    def page(self, label: str | None, key: str | None, rel_type: str, out: bool, skip: int, take: int, by_name: bool = False,
             source: dict[str, Any] | None = None, bundle_min: int | None = None) -> dict[str, Any]:
        """``take`` relationships from ``skip`` on; ``by_name``: ``take`` neighbour names (big ones as bundles) and
        ``next`` – the offset where the following page begins."""
        rel_type = check_name(rel_type, "ryšio tipas")
        src = source or {"label": check_name(label, "etiketė"), "key": key}
        if by_name or "bundle" in src:
            return self._names_page(src, rel_type, out, self._name_runs(src, rel_type, out), int(skip), int(take), bundle_min)
        label = src["label"]
        pattern = f"(n)-[r:`{rel_type}`]->(m)" if out else f"(n)<-[r:`{rel_type}`]-(m)"
        rows = self.read(
            f"MATCH (n:`{label}` {{key: $key}}) MATCH {pattern}{self._where('m')} "
            "WITH n, r, m ORDER BY coalesce(m.display_name, m.key), m.key, elementId(r) SKIP $skip LIMIT $take "
            "RETURN labels(n) AS nl, r, m, COUNT { (m)--() } AS deg", key=key, skip=int(skip), take=int(take))
        nodes, edges = {}, []
        for row in rows:   # the centre's whole node is not sent with each of up to a thousand rows: its id is enough
            n, m = _ref(row["nl"], key), node_out(row["m"], row["deg"])
            nodes[m["id"]] = m
            edges.append(rel_out(row["r"], n if out else m, m if out else n))
        return {"nodes": list(nodes.values()), "edges": edges, "next": int(skip) + len(edges)}

    def bundle_members(self, src: dict[str, Any], skip: int = 0, take: int = 50) -> dict[str, Any]:
        """A page of the nodes a bundle stands for (by key), with the bundle's relationship counts."""
        if "bundle" not in src:
            raise ValueError("ne pluoštas")
        q, params = self._source(src)
        rows = self.read(f"{q} WITH n ORDER BY n.key SKIP $skip LIMIT $take RETURN n, COUNT {{ (n)--() }} AS deg",
                         skip=int(skip), take=int(take), **params)
        return {"id": self.source_id(src), "members": [node_out(r["n"], r["deg"]) for r in rows],
                "relationship_counts": self.bundle_counts(src)}

    # What the map of a node shows (🗺 with a Sense, a CognateSet or a merged node selected): Cypher continuing from
    # ``b`` (the chosen node or nodes) that binds every node ``n`` to be placed; the labels ``n`` may have.
    MAP_WAYS: dict[str, tuple[str, tuple[str, ...]]] = {
        # a sense: its lemmas (lexemes); a sense with no lexeme (LKEŽDB): its forms
        "lemmas": ("CALL (b) { MATCH (b)<-[:HAS_SENSE]-(n:Lexeme) RETURN n UNION "
                   "MATCH (b)<-[:HAS_SENSE]-(n:Form) WHERE NOT EXISTS { (b)<-[:HAS_SENSE]-(:Lexeme) } RETURN n }",
                   ("Lexeme", "Form")),
        # a sense: its concept (with the same concept of the other datasets, CORRESPONDS_TO), every sense of it, their forms
        "concept_forms": ("MATCH (b)-[:DENOTES]->(:Concept)-[:CORRESPONDS_TO*0..2]-(c:Concept) WITH DISTINCT c "
                          "MATCH (c)<-[:DENOTES]-(s:Sense) WITH DISTINCT s "
                          "CALL (s) { MATCH (s)<-[:HAS_SENSE]-(:Lexeme)-[:HAS_FORM]->(n:Form) RETURN n UNION "
                          "MATCH (s)<-[:HAS_SENSE]-(n:Form) RETURN n }", ("Form",)),
        # a concept (with the same concept of the other datasets): every sense of it, their lemmas (a sense without a lexeme:
        # its forms)
        "concept_lemmas": ("MATCH (b)-[:CORRESPONDS_TO*0..2]-(c:Concept) WITH DISTINCT c "
                           "MATCH (c)<-[:DENOTES]-(s:Sense) WITH DISTINCT s "
                           "CALL (s) { MATCH (s)<-[:HAS_SENSE]-(n:Lexeme) RETURN n UNION "
                           "MATCH (s)<-[:HAS_SENSE]-(n:Form) WHERE NOT EXISTS { (s)<-[:HAS_SENSE]-(:Lexeme) } RETURN n }",
                           ("Lexeme", "Form")),
        # a cognate set: its forms
        "cognate_forms": ("MATCH (b)<-[:COGNATE_IN]-(n:Form)", ("Form",)),
    }

    def _map_points(self, q: str, params: dict[str, Any], labels: tuple[str, ...], geo_paths: list[dict[str, Any]]) -> dict[str, Any]:
        """The nodes ``n`` bound by ``q`` (distinct) with their coordinates – their own, else over the geo paths – for the
        map: only what a point needs (no properties), at most ``MAP_POINTS``."""
        labels = tuple(check_name(lab, "etiketė") for lab in labels)
        label_expr = f"'{labels[0]}'" if len(labels) == 1 else \
            "CASE " + " ".join(f"WHEN n:`{lab}` THEN '{lab}'" for lab in labels[:-1]) + f" ELSE '{labels[-1]}' END"
        total = self.read(f"{q} RETURN count(n) AS c", **params)[0]["c"]
        found: dict[tuple[str, str], dict[str, Any]] = {}
        own = self.read(f"{q} WITH n LIMIT $max RETURN n.key AS key, {label_expr} AS label, coalesce(n.display_name, n.key) AS name, "
                        "n.dataset AS ds, n.latitude AS lat, n.longitude AS lon", max=self.MAP_POINTS, **params)
        for r in own:
            found[(r["label"], r["key"])] = {"label": r["label"], "key": r["key"], "display_name": r["name"], "dataset": r["ds"],
                                             "lat": r["lat"], "lon": r["lon"], "via": None}
        for label in labels:
            for pattern in [check_pattern(g["pattern"]) for g in geo_paths if g.get("label") == label]:
                keys = [k for (lab, k), p in found.items() if lab == label and (p["lat"] is None or p["lon"] is None)]
                if not keys:
                    break
                rows = self.read(
                    f"UNWIND $keys AS k MATCH (n:`{label}` {{key: k}}) OPTIONAL MATCH {pattern} "
                    f"WHERE t.latitude IS NOT NULL AND t.longitude IS NOT NULL{self._and('t')} "
                    "WITH k, collect(t)[0] AS t WHERE t IS NOT NULL "
                    "RETURN k, t.latitude AS lat, t.longitude AS lon, coalesce(t.display_name, t.name, t.key) AS name", keys=keys)
                for r in rows:
                    found[(label, r["k"])].update(lat=r["lat"], lon=r["lon"], via=r["name"])
        points = []
        for p in found.values():
            try:
                lat, lon = float(p["lat"]), float(p["lon"])
            except (TypeError, ValueError):
                continue
            points.append([p["key"], p["display_name"], round(lat, 5), round(lon, 5), p["via"], p["dataset"], p["label"]])
        # [key, name, latitude, longitude, the place's name, dataset, label]: thousands of points travel as short rows
        shown = {p[6] for p in points} or set(labels[:1])
        return {"label": labels[0] if len(shown) > 1 else next(iter(shown)), "labels": sorted(shown), "total": total,
                "points": points, "without": len(found) - len(points), "truncated": total > len(found)}

    def bundle_map(self, src: dict[str, Any], geo_paths: list[dict[str, Any]], lexemes: bool | None = None) -> dict[str, Any]:
        """Every member of a bundle with its coordinates – of Sense bundles the lemmas (``MAP_WAYS["lemmas"]``)."""
        if "bundle" not in src:
            raise ValueError("ne pluoštas")
        q, params = self._source(src, "b")
        lexemes = src["bundle"].get("label") == "Sense" if lexemes is None else lexemes
        if lexemes:
            way, labels = self.MAP_WAYS["lemmas"]
            q += f" {way} WITH DISTINCT n{self._where('n')}"
        else:
            q += " WITH b AS n"
            labels = (src["bundle"]["label"],)
        return {"id": self.source_id(src), **self._map_points(q, params, labels, geo_paths)}

    def related_map(self, refs: list[dict[str, str]] | None, way: str, geo_paths: list[dict[str, Any]],
                    bundle: dict[str, Any] | None = None) -> dict[str, Any]:
        """The nodes related to these nodes (all of one label) – or to a bundle's members – the ``way`` says
        (``MAP_WAYS``), for the map."""
        if way not in self.MAP_WAYS:
            raise ValueError(f"nežinomas žemėlapio būdas: {way}")
        cont, shown = self.MAP_WAYS[way]
        if bundle is not None:
            q, params = self._source(bundle, "b")
        else:
            labels = {r["label"] for r in refs or []}
            if len(labels) != 1:
                raise ValueError("žemėlapiui reikia vienos rūšies mazgų")
            label = check_name(labels.pop(), "etiketė")
            q, params = f"UNWIND $keys AS k MATCH (b:`{label}` {{key: k}}){self._where('b')}", {"keys": [r["key"] for r in refs][:2000]}
        q += f" WITH DISTINCT b {cont} WITH DISTINCT n{self._where('n')}"
        return {"way": way, **self._map_points(q, params, shown, geo_paths)}

    def nodes(self, refs: list[dict[str, str]]) -> list[dict[str, Any]]:
        out = []
        for label in sorted({r["label"] for r in refs}):
            keys = [r["key"] for r in refs if r["label"] == label]
            rows = self.read(f"UNWIND $keys AS k MATCH (n:`{check_name(label, 'etiketė')}` {{key: k}}){self._where('n')} "
                             "RETURN n, COUNT { (n)--() } AS deg", keys=keys)
            out.extend(node_out(r["n"], r["deg"]) for r in rows)
        return out

    def neighbors(self, refs: list[dict[str, str]], rel_type: str, out: bool, label: str | None = None, limit: int = 2000) -> dict[str, Any]:
        """Neighbours of several nodes over one relationship type (e.g. the lexemes of a merged sense node's senses)."""
        rel_type = check_name(rel_type, "ryšio tipas")
        end = f":`{check_name(label, 'etiketė')}`" if label else ""
        pattern = f"(n)-[r:`{rel_type}`]->(m{end})" if out else f"(n)<-[r:`{rel_type}`]-(m{end})"
        nodes, edges = {}, []
        for lab in sorted({r["label"] for r in refs}):
            keys = [r["key"] for r in refs if r["label"] == lab]
            rows = self.read(f"UNWIND $keys AS k MATCH (n:`{check_name(lab, 'etiketė')}` {{key: k}}) MATCH {pattern}{self._where('m')} "
                             "RETURN labels(n) AS nl, k, r, m, COUNT { (m)--() } AS deg LIMIT $limit", keys=keys, limit=int(limit))
            for row in rows:
                n, m = _ref(row["nl"], row["k"]), node_out(row["m"], row["deg"])
                nodes[m["id"]] = m
                edges.append(rel_out(row["r"], n if out else m, m if out else n))
        return {"nodes": list(nodes.values()), "edges": edges}

    def _element_ids(self, ids: list[str]) -> list[str]:
        by_label: dict[str, list[str]] = {}
        for i in ids:
            if "|" in i:
                label, key = i.split("|", 1)
                if NAME.match(label):
                    by_label.setdefault(label, []).append(key)
        if not by_label:
            return []
        queries = [(f"UNWIND $keys AS k MATCH (n:`{label}` {{key: k}}){self._where('n')} RETURN elementId(n) AS e", {"keys": keys})
                   for label, keys in by_label.items()]
        return [r["e"] for rows in self.read_many(queries) for r in rows]

    def edges_between(self, ids: list[str], types: list[str] | None = None, focus: list[str] | None = None) -> list[dict[str, Any]]:
        """Relationships among nodes already in the garden (so a path or an added node connects to what is shown).
        ``focus``: only those touching these nodes (the ones just added) – from them outwards, not every pair of the garden."""
        eids = self._element_ids(ids)
        if len(eids) < 2:
            return []
        types = [check_name(t, "ryšio tipas") for t in types] if types else None
        if focus is not None:
            feids = self._element_ids([i for i in focus if i in set(ids)])
            if not feids:
                return []
            rows = self.read(
                "MATCH (x) WHERE elementId(x) IN $feids MATCH (y) WHERE elementId(y) IN $eids AND y <> x "
                "MATCH (x)-[r]-(y) WHERE $types IS NULL OR type(r) IN $types WITH DISTINCT r "
                f"{ENDS} LIMIT 3000", eids=eids, feids=feids, types=types)
        else:
            rows = self.read(
                "MATCH (x) WHERE elementId(x) IN $eids MATCH (y) WHERE elementId(y) IN $eids AND elementId(x) < elementId(y) "
                "MATCH (x)-[r]-(y) WHERE $types IS NULL OR type(r) IN $types "
                f"{ENDS} LIMIT 3000", eids=eids, types=types)
        return [rel_out(r["r"], _ref(r["sl"], r["sk"]), _ref(r["el"], r["ek"])) for r in rows]

    # -- paths -----------------------------------------------------------------------------
    def paths(self, a: dict[str, str], b: dict[str, str], excluded: list[str], limit: int = 50) -> dict[str, Any]:
        """Every shortest path between two nodes, however long (no length limit: the shortest one is always looked for)."""
        la, lb = check_name(a["label"], "etiketė"), check_name(b["label"], "etiketė")
        excluded = [check_name(t, "ryšio tipas") for t in excluded]
        rows = self.read(
            f"MATCH (a:`{la}` {{key: $ka}}), (b:`{lb}` {{key: $kb}}) WHERE a <> b "
            "MATCH p = allShortestPaths((a)-[*]-(b)) "
            "WHERE none(r IN relationships(p) WHERE type(r) IN $excluded)" + ("" if self.whole else f" AND all(x IN nodes(p) WHERE {self.ok('x')})") + " "
            "RETURN p LIMIT $limit", ka=a["key"], kb=b["key"], excluded=excluded, limit=int(limit))
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        paths = []
        for row in rows:
            p = row["p"]
            pnodes = [node_out(n) for n in p.nodes]
            by_eid = {n.element_id: out for n, out in zip(p.nodes, pnodes)}
            pedges = [rel_out(r, by_eid[r.start_node.element_id], by_eid[r.end_node.element_id]) for r in p.relationships]
            nodes.update({n["id"]: n for n in pnodes})
            edges.update({e["id"]: e for e in pedges})
            paths.append({"nodes": [n["id"] for n in pnodes], "edges": [e["id"] for e in pedges]})
        if nodes:
            for n in self.nodes([{"label": x["label"], "key": x["key"]} for x in nodes.values()]):
                nodes[n["id"]]["degree"] = n["degree"]
        return {"paths": paths, "nodes": list(nodes.values()), "edges": list(edges.values()), "excluded": excluded,
                "length": len(paths[0]["edges"]) if paths else None, "truncated": len(paths) >= limit}

    # -- computed properties ----------------------------------------------------------------
    def computed(self, defs: list[dict[str, Any]], refs: list[dict[str, str]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
        out: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for d in defs:
            label = check_name(d.get("label"), "etiketė")
            name = check_name(d.get("name"), "savybės vardas")
            pattern = check_pattern(d.get("pattern", ""))
            keys = [r["key"] for r in refs if r["label"] == label]
            if not keys:
                continue
            rows = self.read(
                f"UNWIND $keys AS k MATCH (n:`{label}` {{key: k}}) OPTIONAL MATCH {pattern} "
                f"WITH k, t WHERE t IS NOT NULL{self._and('t')} "
                "RETURN k, collect(DISTINCT {key: t.key, label: head(labels(t)), name: coalesce(t.display_name, t.name, t.key), "
                "glottocode: t.glottocode})[0..5] AS vals",
                keys=keys)
            for row in rows:
                if row["vals"]:
                    out.setdefault(node_id(label, row["k"]), {})[name] = row["vals"]
        return out

    def geo(self, defs: list[dict[str, Any]], refs: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
        """Coordinates for nodes without their own: from the first node ``t`` with latitude/longitude on a geo path."""
        out: dict[str, dict[str, Any]] = {}
        for d in defs:
            label = check_name(d.get("label"), "etiketė")
            pattern = check_pattern(d.get("pattern", ""))
            keys = [r["key"] for r in refs if r["label"] == label and node_id(label, r["key"]) not in out]
            if not keys:
                continue
            rows = self.read(
                f"UNWIND $keys AS k MATCH (n:`{label}` {{key: k}}) OPTIONAL MATCH {pattern} "
                f"WHERE t.latitude IS NOT NULL AND t.longitude IS NOT NULL{self._and('t')} "
                "WITH k, collect(t)[0] AS t WHERE t IS NOT NULL "
                "RETURN k, t.latitude AS lat, t.longitude AS lon, head(labels(t)) AS label, t.key AS key, "
                "coalesce(t.display_name, t.name, t.key) AS name", keys=keys)
            for row in rows:
                out[node_id(label, row["k"])] = {"latitude": row["lat"], "longitude": row["lon"],
                                                 "via": {"label": row["label"], "key": row["key"], "name": row["name"]}}
        return out

    # -- writes ----------------------------------------------------------------------------------
    def create_relationship(self, a: dict[str, str], b: dict[str, str], rel_type: str, note: str | None,
                            key: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Curated relationship drawn by the researcher (Ctrl+J); provenance says who/where, not a source row."""
        from neo4j import unit_of_work
        la, lb = check_name(a["label"], "etiketė"), check_name(b["label"], "etiketė")
        check_rel_type(rel_type)
        props = {"key": key or "curated:" + str(uuid.uuid4()), "dataset": ADDITIONS, "rule_id": "sodas-manual-v1",
                 "status": "curated", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **(extra or {})}
        if note:
            props["note"] = str(note)[:2000]
        driver, database = self.driver()
        with driver.session(database=database) as session:
            @unit_of_work(timeout=READ_TIMEOUT)
            def work(tx):
                return list(tx.run(
                    f"MATCH (a:`{la}` {{key: $ka}}), (b:`{lb}` {{key: $kb}}) CREATE (a)-[r:`{rel_type}`]->(b) SET r = $props "
                    "RETURN r, a, b", ka=a["key"], kb=b["key"], props=props))
            rows = session.execute_write(work)
        self.forget_schema()   # perhaps a new type
        if not rows:
            raise LookupError("vienas iš mazgų nerastas")
        return rel_out(rows[0]["r"], node_out(rows[0]["a"]), node_out(rows[0]["b"]))

    def _drawn(self, end: dict[str, str] | None) -> tuple[str, dict[str, Any]]:
        """The pattern of a relationship drawn in the garden: from one of its ends when known (an index lookup and that
        node's relationships), else by key over every relationship of the database (minutes once it is large)."""
        if end and end.get("label") and end.get("key"):
            return f"(a:`{check_name(end['label'], 'etiketė')}` {{key: $end}})-[r {{key: $key}}]-(b)", {"end": str(end["key"])}
        return "(a)-[r {key: $key}]->(b)", {}

    def curated_relationship(self, key: str, end: dict[str, str] | None = None) -> dict[str, Any] | None:
        """A relationship drawn in the garden (``dataset`` = Papildymai), found by its key (``end``: one of its nodes)."""
        pattern, params = self._drawn(end)
        rows = self.read(f"MATCH {pattern} WHERE r.dataset IN $ds RETURN r, startNode(r) AS s, endNode(r) AS e LIMIT 1",
                         key=str(key), ds=[ADDITIONS], **params)
        return rel_out(rows[0]["r"], node_out(rows[0]["s"]), node_out(rows[0]["e"])) if rows else None

    def delete_relationship(self, key: str, end: dict[str, str] | None = None) -> int:
        """Removes a relationship drawn in the garden (only ``dataset`` = Papildymai: imported data are never deleted here)."""
        from neo4j import unit_of_work
        pattern, params = self._drawn(end)
        driver, database = self.driver()
        with driver.session(database=database) as session:
            @unit_of_work(timeout=READ_TIMEOUT)
            def work(tx):
                return tx.run(f"MATCH {pattern} WHERE r.dataset IN $ds WITH DISTINCT r DELETE r RETURN count(*) AS n",
                              key=str(key), ds=[ADDITIONS], **params).single()["n"]
            return int(session.execute_write(work) or 0)
