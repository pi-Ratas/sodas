"""Which datasets a piece of work used: every garden and every Vaiva run keeps its own record (``sources``).

A garden's record grows with every save from the nodes and relationships in it (a node keeps its ``dataset``). A Vaiva
run's record is gathered while it runs: ``Tracker.wrap(read)`` looks at every Cypher query that found something and at
its answer – dataset names written in the query or given as a parameter (``ds="datsemshift"``), node keys in the answer
(``iecor:form:…``; ``languoid:…`` is Glottolog), ``dataset`` columns, nodes with a ``dataset`` property – and the study
(or a workshop part) may name datasets it reads otherwise (CLTS). Keys given as parameters are not counted (they are
what is asked about, not what was read), nor is the answer of a query that only finds the scope of a study – the
languages under a Glottolog branch, whatever dataset they come from: such a query starts with ``/* apimtis */``.

The record is ``{dataset: {"first": iso, "last": iso, "versions": ["v1.2", …]}}``: a dataset once used stays in it
(it was used for the work even if its nodes left the garden later). The bibliography (``bibliografija``) is made from it.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from datetime import datetime, timezone

# key prefixes that are not the dataset's own name
KEY_PREFIX = {"languoid": "glottolog"}
# not datasets to cite: relationships drawn in the garden, import runs
NOT_CITED = {"Papildymai", "run", "curated", "sodas-rysys"}
MAX_SOURCES = 60
_DS = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")


def dataset_of_key(key: Any, known: Iterable[str] | None = None) -> str | None:
    """The dataset of a node key (``iecor:form:1`` → iecor, ``languoid:aala1237`` → glottolog, ``lkezdb@1`` → lkezdb)."""
    if not isinstance(key, str) or not key:
        return None
    head = re.split(r"[:@]", key, 1)[0]
    if head == key or not _DS.match(head):
        return None
    ds = KEY_PREFIX.get(head, head)
    if known is not None and ds not in known:
        return None
    return ds if ds not in NOT_CITED else None


def _clean_ds(ds: Any) -> str | None:
    if not isinstance(ds, str) or not _DS.match(ds) or ds in NOT_CITED:
        return None
    return ds


def garden_datasets(garden: dict[str, Any]) -> set[str]:
    """Datasets of the nodes and relationships now in a garden."""
    out: set[str] = set()
    for n in garden.get("nodes") or []:
        d = n.get("data") if isinstance(n, dict) else None
        if not isinstance(d, dict) or d.get("kind") == "more":
            continue
        ds = _clean_ds(d.get("dataset")) or dataset_of_key(d.get("key"))
        for twin in d.get("datasets") or []:          # two datasets' nodes shown as one
            if _clean_ds(twin):
                out.add(twin)
        if ds:
            out.add(ds)
    for e in garden.get("edges") or []:
        d = e.get("data") if isinstance(e, dict) else None
        props = d.get("props") if isinstance(d, dict) else None
        ds = _clean_ds(props.get("dataset")) if isinstance(props, dict) else None
        if ds:
            out.add(ds)
    return out


def clean_sources(value: Any) -> dict[str, dict[str, Any]]:
    """A record from outside (a garden file): only well-formed entries are kept."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(value, dict):
        return out
    for ds, entry in list(value.items())[:MAX_SOURCES]:
        if not _clean_ds(ds) or not isinstance(entry, dict):
            continue
        versions = [str(v)[:40] for v in entry.get("versions") or [] if isinstance(v, (str, int, float)) and str(v).strip()][:10]
        out[ds] = {"first": str(entry.get("first") or "")[:40] or None, "last": str(entry.get("last") or "")[:40] or None,
                   "versions": versions}
    return out


def union_sources(*records: Any) -> dict[str, dict[str, Any]]:
    """Several records as one: the earliest „first“, the latest „last“, all the versions."""
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        for ds, e in clean_sources(rec).items():
            have = out.get(ds)
            if have is None:
                out[ds] = e
                continue
            have["first"] = min(x for x in (have["first"], e["first"]) if x) if have["first"] or e["first"] else None
            have["last"] = max(x for x in (have["last"], e["last"]) if x) if have["last"] or e["last"] else None
            have["versions"] += [v for v in e["versions"] if v not in have["versions"]]
    return dict(list(out.items())[:MAX_SOURCES])


def merge_sources(old: Any, found: Iterable[str], versions: dict[str, dict[str, Any]] | None = None,
                  when: str | None = None) -> dict[str, dict[str, Any]]:
    """``old`` with the datasets ``found`` now: new ones are added, those used again get a new „last“ (and the version
    of the dataset now, when known)."""
    out = clean_sources(old)
    when = when or datetime.now(timezone.utc).isoformat(timespec="seconds")
    for ds in sorted(set(found)):
        if not _clean_ds(ds):
            continue
        e = out.setdefault(ds, {"first": when, "last": when, "versions": []})
        e["last"] = when
        e["first"] = e.get("first") or when
        v = ((versions or {}).get(ds) or {}).get("version")
        if v and v not in e["versions"]:
            e["versions"].append(v)
    return dict(list(out.items())[:MAX_SOURCES])


# ---------------------------------------------------------------- following a run
_LITERAL = re.compile(r"""['"]([A-Za-z0-9_.-]{2,40})(?:[:@][^'"]*)?['"]""")
SCOPE = "/* apimtis */"      # a query that finds the scope of a study (see the module's description)


class Tracker:
    """Collects the datasets a run touches (``found``); ``wrap(read)`` gives a ``read`` that reports to it."""

    def __init__(self, known: Iterable[str]):
        self.known = {k for k in known if _clean_ds(k)}
        self.found: set[str] = set()
        prefixes = sorted(self.known | set(KEY_PREFIX), key=len, reverse=True)
        self._key = re.compile(r"^(%s)[:@]" % "|".join(map(re.escape, prefixes))) if prefixes else None
        self._lock = threading.Lock()

    def add(self, *datasets: str | None) -> None:
        with self._lock:
            self.found.update(d for d in datasets if _clean_ds(d))

    def child(self) -> "Tracker":
        t = Tracker(())
        t.known, t._key = self.known, self._key
        return t

    def _text(self, s: str, seen: set[str]) -> None:
        """A node key (``iecor:form:1``). A bare dataset name counts only as a ``dataset`` value: a form „wold“ or a
        transcription system „phoible“ is not a use of WOLD or PHOIBLE."""
        if self._key is not None and len(s) < 400 and " " not in s:
            m = self._key.match(s)
            if m and len(s) > len(m.group(0)):
                seen.add(KEY_PREFIX.get(m.group(1), m.group(1)))

    def _value(self, v: Any, seen: set[str], depth: int = 0) -> None:
        if isinstance(v, str):
            self._text(v, seen)
        elif isinstance(v, (list, tuple)):
            if depth < 3:
                for x in v[:200]:
                    self._value(x, seen, depth + 1)
        elif isinstance(v, dict):
            if depth < 3:
                for k, x in list(v.items())[:60]:
                    if k == "dataset" and isinstance(x, str):
                        seen.add(x)
                    else:
                        self._value(x, seen, depth + 1)
        elif hasattr(v, "labels") and hasattr(v, "get"):          # a Neo4j node
            ds = v.get("dataset") or dataset_of_key(v.get("key"), self.known)
            if isinstance(ds, str):
                seen.add(ds)

    def look(self, query: str, params: dict[str, Any], rows: list[Any]) -> None:
        """One query and its answer: what it read (only when it found something)."""
        if not rows or query.lstrip().startswith(SCOPE):
            return
        seen: set[str] = set()
        for m in _LITERAL.finditer(query):
            word = m.group(1)
            if word in self.known:
                seen.add(word)
            elif word in KEY_PREFIX:
                seen.add(KEY_PREFIX[word])
        for v in params.values():
            if isinstance(v, str) and v in self.known:
                seen.add(v)
        for r in rows:
            items = r.items() if hasattr(r, "items") else enumerate(r)
            for k, v in items:
                if k in ("dataset", "ds") and isinstance(v, str):
                    seen.add(v)
                else:
                    self._value(v, seen)
        self.add(*(s for s in seen if s in self.known or s in KEY_PREFIX.values()))

    def wrap(self, read: Callable[..., list[Any]]) -> Callable[..., list[Any]]:
        raw = getattr(read, "raw", read)

        def tracked(query: str, **params):
            rows = raw(query, **params)
            self.look(query, params, rows)
            return rows
        tracked.raw = raw            # type: ignore[attr-defined]
        tracked.tracker = self       # type: ignore[attr-defined]
        return tracked


# ---------------------------------------------------------------- versions of the datasets on this computer
_versions: dict[str, Any] = {"at": 0.0, "value": {}}
_versions_lock = threading.Lock()
VERSIONS_SECONDS = 600


def _git(path: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def dataset_version(path: Path) -> dict[str, Any]:
    """The release of a dataset folder: its git tag (``v1.2``) and that tag's date; else what its metadata says."""
    out: dict[str, Any] = {}
    if not path.is_dir():
        return out
    if (path / ".git").exists():
        tag = _git(path, "describe", "--tags", "--abbrev=0")
        if tag:
            out["version"] = tag
            day = _git(path, "log", "-1", "--format=%cs", tag)
            if day:
                out["date"] = day
            exact = _git(path, "describe", "--tags", "--exact-match")
            if not exact:
                out["commit"] = _git(path, "rev-parse", "--short", "HEAD") or None
    if "version" not in out:
        for name in (".zenodo.json", "metadata.json"):
            try:
                meta = json.loads((path / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            v = meta.get("version") if isinstance(meta, dict) else None
            if isinstance(v, str) and v.strip():
                out["version"] = v.strip()
                break
    return out


def dataset_versions(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    """{dataset: {version, date}} for the dataset folders of datasets.yaml (kept for ten minutes)."""
    with _versions_lock:
        if time.time() - _versions["at"] < VERSIONS_SECONDS and _versions.get("paths") == sorted(map(str, paths.values())):
            return _versions["value"]
    value = {ds: v for ds, p in paths.items() if (v := dataset_version(Path(p)))}
    with _versions_lock:
        _versions.update(at=time.time(), value=value, paths=sorted(map(str, paths.values())))
    return value


__all__ = ["Tracker", "clean_sources", "dataset_of_key", "dataset_version", "dataset_versions", "garden_datasets",
           "merge_sources", "union_sources"]
