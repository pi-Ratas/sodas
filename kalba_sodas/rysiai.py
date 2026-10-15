"""Relationships drawn in the garden (Ctrl+J).

A relationship is written to Neo4j at once (dataset „Papildymai“, key ``sodas-rysys:<n>``) and is an edge like any
other. The program keeps its own list of them (``sodas-duomenys/rysiai.json``) for ⚙ → Mano ryšiai and the names
given before: finding them in Neo4j would mean reading every relationship of the database.

Types: a type that Neo4j already has is used as it is; any other name becomes type ``CUSTOM`` with the name in the
property ``label`` (the garden writes that instead of the type), so one's own names do not litter the list of types.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graph import check_name, check_rel_type, node_id

KEY_PREFIX = "sodas-rysys:"
CUSTOM = "CUSTOM"
MAX_LABEL = 100


def rel_key(rid: int) -> str:
    return f"{KEY_PREFIX}{rid}"


class Relationships:
    def __init__(self, root: Path, graph):
        self.path = root / "rysiai.json"
        self.graph = graph
        self.lock = threading.Lock()
        self._types: tuple[float, set[str]] = (0.0, set())

    def _load(self) -> list[dict[str, Any]]:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        except (json.JSONDecodeError, OSError):
            rows = []
        return [r for r in rows if isinstance(r, dict)]

    def _save(self, rows: list[dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def known_types(self) -> set[str]:
        """Relationship types Neo4j has (asked at most once a minute)."""
        at, types = self._types
        if not at or time.monotonic() - at > 60:
            try:
                types = set(self.graph.schema().get("types") or [])
            except Exception:  # noqa: BLE001 – Neo4j away: every new name becomes CUSTOM
                types = set()
            self._types = (time.monotonic(), types)
        return types

    def type_and_label(self, text: Any) -> tuple[str, str | None]:
        """The name chosen: a type Neo4j has (any case), else CUSTOM with this name as its label."""
        name = " ".join(str(text or "").split())
        if not name:
            raise ValueError("nurodykite ryšio pavadinimą")
        if len(name) > MAX_LABEL:
            raise ValueError(f"ryšio pavadinimas per ilgas (daugiausia {MAX_LABEL} ženklų)")
        known = {t.upper(): t for t in self.known_types() if t != CUSTOM}
        if name.upper() in known:
            return check_rel_type(known[name.upper()]), None
        return CUSTOM, name

    @staticmethod
    def out(r: dict[str, Any]) -> dict[str, Any]:
        a, b = r["a"], r["b"]
        return {**r, "name": r.get("label") or r["type"],
                "a": {**a, "id": node_id(a["label"], a["key"])}, "b": {**b, "id": node_id(b["label"], b["key"])}}

    def create(self, a: dict[str, str], b: dict[str, str], rel_type: str, note: str | None) -> dict[str, Any]:
        """A new relationship between two nodes, written to Neo4j."""
        if (a.get("label"), a.get("key")) == (b.get("label"), b.get("key")):
            raise ValueError("ryšys turi jungti du skirtingus mazgus")
        rel_type, label = self.type_and_label(rel_type)
        found = self.graph.nodes([{"label": check_name(str(x.get("label") or ""), "etiketė"), "key": str(x.get("key") or "")} for x in (a, b)])
        names = {str(n["key"]): n.get("display_name") for n in found}
        if str(a.get("key")) not in names or str(b.get("key")) not in names:
            raise LookupError("vienas iš mazgų nerastas")
        note = str(note or "").strip()[:2000] or None
        with self.lock:
            rows = self._load()
            rid = max((int(r.get("id") or 0) for r in rows), default=0) + 1
            edge = self.graph.create_relationship(a, b, rel_type, note, key=rel_key(rid), extra={"label": label} if label else None)
            rows.append({"id": rid, "key": rel_key(rid), "type": rel_type, "label": label, "note": note,
                         "a": {"label": a["label"], "key": str(a["key"]), "name": names[str(a["key"])]},
                         "b": {"label": b["label"], "key": str(b["key"]), "name": names[str(b["key"])]},
                         "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            self._save(rows)
        return edge

    def mine(self) -> list[dict[str, Any]]:
        return [self.out(r) for r in sorted(self._load(), key=lambda r: r.get("created_at") or "", reverse=True)]

    def get(self, rid: Any) -> dict[str, Any]:
        for r in self._load():
            if str(r.get("id")) == str(rid):
                return self.out(r)
        raise LookupError("ryšys nerastas")

    def delete(self, key: str, end: dict[str, str] | None = None) -> dict[str, Any]:
        """By its key: a relationship drawn in the garden (also an older one, not on the list). ``end``: one of its nodes
        ({label, key}) – Neo4j finds the relationship from it instead of reading all of them."""
        with self.lock:
            rows = self._load()
            row = next((r for r in rows if r.get("key") == key), None)
            if row is not None and not end:
                end = {"label": row["a"]["label"], "key": row["a"]["key"]}
            if row is None and not self.graph.curated_relationship(key, end):
                raise LookupError("ryšys nerastas (ištrinti galima tik sode nubrėžtus ryšius)")
            n = self.graph.delete_relationship(key, end)
            if row is not None:
                self._save([r for r in rows if r is not row])
        return {"deleted": key, "neo4j": n}

    def my_labels(self) -> list[str]:
        """Names given to one's own CUSTOM relationships (offered again when drawing a new one)."""
        return sorted({r["label"] for r in self._load() if r.get("label")}, key=str.lower)
