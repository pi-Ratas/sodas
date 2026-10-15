"""Persistence of the garden: settings, gardens (sodai), drafts, uploaded pictures and the error log – JSON files in the
data directory (``sodas-duomenys``): ``settings.json``, ``gardens/*.json``, ``images/``, ``juodrasciai.json`` and
``zurnalas.jsonl``."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import sekimas

IMAGE_TYPES = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024
GARDEN_ID = re.compile(r"^[a-z0-9]{4,32}$")
GARDEN_FILE = "sodo-byla/1"      # a garden downloaded to share it (Tvarkyti sodus → ⬇ / ⬆)
GARDEN_KEYS = ("name", "excluded", "basket", "typeVis", "labelHidden", "unmerged", "untwinned", "manual", "nodes", "edges", "viewport")
DRAFT_KINDS = ("dirbtuves",)     # unsaved work of a page kept (Vaivos dirbtuvių drobė)
MAX_DRAFT_BYTES = 512 * 1024

# Language of a lexical node, reached through the imported research graph (contract §3).
DEFAULT_COMPUTED = [
    {"name": "language", "label": "Lexeme", "pattern": "(n)-[:USED_IN]->(t:Languoid)", "image_from_target": True},
    {"name": "language", "label": "Form", "pattern": "(n)<-[:HAS_FORM]-(:Lexeme)-[:USED_IN]->(t:Languoid)", "image_from_target": True},
    {"name": "language", "label": "Sense", "pattern": "(n)<-[:HAS_SENSE]-(:Lexeme)-[:USED_IN]->(t:Languoid)", "image_from_target": True},
    # LKEŽDB forms without a lexeme name their language directly
    {"name": "language", "label": "Form", "pattern": "(n)-[:USED_IN]->(t:Languoid)", "image_from_target": True},
]
COMPUTED_VERSION = 2   # raise when DEFAULT_COMPUTED gets a new path: saved lists receive it once

# A form or lexeme lies where its language lies (the map, contract §3).
DEFAULT_GEO_PATHS = [
    {"label": "Form", "pattern": "(n)<-[:HAS_FORM]-(:Lexeme)-[:USED_IN]->(t:Languoid)"},
    {"label": "Lexeme", "pattern": "(n)-[:USED_IN]->(t:Languoid)"},
    {"label": "Sense", "pattern": "(n)<-[:HAS_SENSE]-(:Lexeme)-[:USED_IN]->(t:Languoid)"},
    {"label": "Form", "pattern": "(n)-[:USED_IN]->(t:Languoid)"},
]
GEO_PATHS_VERSION = 3   # raise when DEFAULT_GEO_PATHS gets a new label: saved lists receive it once

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": {
        "mode": "sun",              # light | dark | sun
        # colours are kept per theme: tuning the light theme does not change the dark one
        # contrast: how far apart the surfaces are (50 – as the colours were before it); custom: colours set one by one
        "light": {"base": {"h": 40, "s": 12, "l": 60}, "accent": {"h": 210, "s": 50, "l": 38}, "contrast": 50, "custom": {}},
        "dark": {"base": {"h": 40, "s": 12, "l": 60}, "accent": {"h": 210, "s": 50, "l": 38}, "contrast": 50, "custom": {}},
        "latitude": 54.69, "longitude": 25.28,   # for "sun" mode (Vilnius)
    },
    "ui": {"fontSize": 14, "nodeLabels": True, "edgeLabels": True},
    # sizeByDegree off -> every node has nodeSize; on -> between min and max by sizeSource; edgeWidth: every
    # relationship's width is multiplied by it (Ctrl+Shift + mouse wheel); boldMerge: forms and lexemes of one name
    # and one language are shown as one node, whatever their datasets ("Drąsiai jungti mazgus")
    "graph": {"minNodeSize": 18, "maxNodeSize": 54, "nodeSize": 30, "badgeSize": 16, "labelSize": 11, "edgeWidth": 1.0, "sizeByDegree": True,
              "sizeSource": "visible", "boldMerge": True},
    # bundleMin: a neighbour name with at least this many nodes comes as one bundle node ("skin ×10963") whose members
    # are not loaded (every name above 1000 does)
    "limits": {"maxNodes": 200, "maxEdges": 600, "maxPerNode": 50, "bundleMin": 21},
    # nodes with latitude/longitude can be shown on a map (off until asked for); opacity of the map tiles.
    # geoPaths: nodes without their own coordinates take them from the first node ``t`` reached by the path
    "map": {"enabled": True, "opacity": 0.7, "geoPaths": copy.deepcopy(DEFAULT_GEO_PATHS), "geoPathsVersion": GEO_PATHS_VERSION},
    "nodeTypes": {
        "Languoid": {"color": "#2f6f9f", "shape": "ellipse"},
        "Society": {"color": "#1f8a8a", "shape": "ellipse"},
        "Lexeme": {"color": "#8a5a2b", "shape": "ellipse"},
        "Form": {"color": "#c0762b", "shape": "ellipse"},
        "Sense": {"color": "#7a4fa0", "shape": "ellipse"},
        "Concept": {"color": "#b0417a", "shape": "ellipse"},
        "CognateSet": {"color": "#3f8f4f", "shape": "hexagon"},
        "ProtoForm": {"color": "#6c9a2f", "shape": "ellipse"},
        "Feature": {"color": "#5a6b8c", "shape": "round-rectangle"},
        "FeatureValue": {"color": "#8898b8", "shape": "round-rectangle"},
        "BorrowingEvent": {"color": "#a0522d", "shape": "triangle"},
        "ExternalIdentifier": {"color": "#d4a017", "shape": "diamond"},
        "SourceRecord": {"color": "#9e9b94", "shape": "round-rectangle"},
    },
    "edgeTypes": {
        "CORRESPONDS_TO": {"style": "dashed"},
        "IDENTIFIED_BY": {"style": "dotted", "width": 1},
    },
    "valueImages": [],              # [{label, property, value, image, title}] – title: the hint over the picture (flags: the country)
    "computed": copy.deepcopy(DEFAULT_COMPUTED), "computedVersion": COMPUTED_VERSION,
    # datasets switched off (⚙ → Duomenynai): their nodes are not looked for and are hidden in gardens
    "datasetsOff": [],
    "pathExcluded": ["IN_TABLE", "IN_RELEASE", "RELEASE_OF", "IMPORTS", "REFERS_TO_RECORD", "FROM_RECORD", "DERIVED_FROM"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Settings written before light/dark colours were separate: copy the one palette to both themes."""
    theme = raw.get("theme") if isinstance(raw, dict) else None
    if isinstance(theme, dict) and ("base" in theme or "accent" in theme):
        theme = dict(theme)
        palette = {k: theme.pop(k) for k in ("base", "accent") if k in theme}
        for mode in ("light", "dark"):
            theme.setdefault(mode, copy.deepcopy(palette))
        raw = {**raw, "theme": theme}
    # a saved list of geo paths replaces the defaults: labels added to the defaults since then are appended once
    m = raw.get("map") if isinstance(raw, dict) else None
    if isinstance(m, dict) and isinstance(m.get("geoPaths"), list) and int(m.get("geoPathsVersion") or 1) < GEO_PATHS_VERSION:
        version = int(m.get("geoPathsVersion") or 1)
        labels = {g.get("label") for g in m["geoPaths"] if isinstance(g, dict)}
        paths = {(g.get("label"), g.get("pattern")) for g in m["geoPaths"] if isinstance(g, dict)}
        new = [g for g in DEFAULT_GEO_PATHS if version < 2 and g["label"] not in labels]   # 2: Lexeme and Sense
        new += [g for g in DEFAULT_GEO_PATHS[3:] if version < 3 and (g["label"], g["pattern"]) not in paths and g not in new]
        m = {**m, "geoPaths": m["geoPaths"] + [copy.deepcopy(g) for g in new], "geoPathsVersion": GEO_PATHS_VERSION}
        raw = {**raw, "map": m}
    if isinstance(raw, dict) and isinstance(raw.get("computed"), list) and int(raw.get("computedVersion") or 1) < COMPUTED_VERSION:
        have = {(c.get("name"), c.get("label"), c.get("pattern")) for c in raw["computed"] if isinstance(c, dict)}
        raw = {**raw, "computed": raw["computed"] + [copy.deepcopy(c) for c in DEFAULT_COMPUTED[3:]
                                                     if (c["name"], c["label"], c["pattern"]) not in have],
               "computedVersion": COMPUTED_VERSION}
    return raw


def _merge(defaults: Any, value: Any) -> Any:
    if isinstance(defaults, dict) and isinstance(value, dict):
        out = copy.deepcopy(defaults)
        for k, v in value.items():
            out[k] = _merge(defaults.get(k), v) if k in defaults else v
        return out
    return copy.deepcopy(value) if value is not None else copy.deepcopy(defaults)


DELETED = {"$nera": True}   # in a change: this key is taken away (e.g. a picture removed)


def _diff(base: Any, value: Any) -> Any:
    """What ``value`` changes in ``base``; ``None`` when nothing. Dicts are compared key by key, the rest whole."""
    if isinstance(base, dict) and isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k not in base:
                out[k] = copy.deepcopy(v)
                continue
            d = _diff(base[k], v)
            if d is not None:
                out[k] = d
        for k in base:
            if k not in value:
                out[k] = dict(DELETED)
        return out or None
    return None if base == value else copy.deepcopy(value)


def _overlay(base: Any, diff: Any) -> Any:
    """``base`` with the differences (``_diff``) laid over it."""
    if isinstance(base, dict) and isinstance(diff, dict):
        out = copy.deepcopy(base)
        for k, v in diff.items():
            if v == DELETED:
                out.pop(k, None)
            else:
                out[k] = _overlay(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(diff) if diff is not None else copy.deepcopy(base)


class Store:
    def __init__(self, root: Path):
        self.root = root
        for sub in ("gardens", "images"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        # {dataset: {version, date}} of the dataset folders (the server gives it; a garden notes the version it used)
        self.dataset_versions: Any = lambda: {}
        self.lock = threading.Lock()
        self._log: deque[dict[str, Any]] = deque(maxlen=1000)
        log_file = root / "zurnalas.jsonl"
        if log_file.exists():
            for line in log_file.read_text(encoding="utf-8").splitlines()[-1000:]:
                try:
                    self._log.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    def _read(self, path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else copy.deepcopy(default)
        except (json.JSONDecodeError, OSError):
            return copy.deepcopy(default)

    def _write(self, path: Path, value: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with self.lock:
            tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)

    # -- settings -------------------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        merged = _merge(DEFAULT_SETTINGS, _migrate(self._read(self.root / "settings.json", {}) or {}))
        merged["datasetsOff"] = sorted({str(d) for d in merged.get("datasetsOff") or [] if isinstance(d, str)})
        return merged

    def save_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("settings must be an object")
        value = dict(value)
        start = value.pop("_from", None)
        if isinstance(start, dict):
            # the page sends the settings it started from: only what it changed since is saved, over the settings as
            # they are now – a tab left open with older settings does not undo changes made in another one
            change = _diff(_merge(DEFAULT_SETTINGS, _migrate(start)), _merge(DEFAULT_SETTINGS, _migrate(value)))
            value = _overlay(self.settings(), change) if change else self.settings()
        self._write(self.root / "settings.json", _merge(DEFAULT_SETTINGS, _migrate(value)))
        return self.settings()

    def reset_settings(self) -> dict[str, Any]:
        """Back to the built-in settings (the datasets switched off stay so)."""
        off = self.settings()["datasetsOff"]
        self._write(self.root / "settings.json", {**copy.deepcopy(DEFAULT_SETTINGS), "datasetsOff": off})
        return self.settings()

    def datasets_off(self) -> list[str]:
        """Datasets switched off (⚙ → Duomenynai)."""
        return self.settings()["datasetsOff"]

    # -- gardens --------------------------------------------------------------------
    @staticmethod
    def new_garden_id() -> str:
        return secrets.token_hex(4)

    def _garden_path(self, garden_id: str) -> Path:
        if not isinstance(garden_id, str) or not GARDEN_ID.match(garden_id):
            raise ValueError("bad garden id")
        return self.root / "gardens" / f"{garden_id}.json"

    @staticmethod
    def _is_blank(garden: dict[str, Any]) -> bool:
        """No nodes and no name: not worth keeping or listing."""
        return not garden.get("nodes") and not str(garden.get("name") or "").strip()

    @staticmethod
    def _clean(value: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in value.items() if k != "_meta"}

    def garden(self, garden_id: str) -> dict[str, Any] | None:
        return self._read(self._garden_path(garden_id))

    def save_garden(self, garden_id: str, value: dict[str, Any]) -> dict[str, Any]:
        path = self._garden_path(garden_id)
        if not isinstance(value, dict):
            raise ValueError("garden must be an object")
        value = self._clean(value)
        if self._is_blank(value):
            self.delete_garden(garden_id)
            return {"id": garden_id, "updated_at": None, "saved": False}
        stamp = _now()
        before = (self._read(path, {}) or {}).get("sources")
        value = {**value, "sources": self._sources(before, value, stamp), "id": garden_id, "updated_at": stamp}
        self._write(path, value)
        return {"id": garden_id, "updated_at": stamp}

    def _sources(self, before: Any, value: dict[str, Any], when: str) -> dict[str, dict[str, Any]]:
        """The garden's record of the datasets it used (``sekimas``): what it had, what came with the value (a garden
        file, a copy) and the datasets of the nodes and relationships in it now."""
        try:
            versions = self.dataset_versions() or {}
        except Exception:  # noqa: BLE001 – the versions are a nicety: the use is noted without them
            versions = {}
        return sekimas.merge_sources(sekimas.union_sources(before, value.get("sources")), sekimas.garden_datasets(value), versions, when)

    def duplicate_garden(self, garden_id: str, name: str | None = None) -> dict[str, Any]:
        source = self.garden(garden_id)
        if source is None:
            raise LookupError("sodas nerastas")
        copy_name = name or f"{source.get('name') or garden_id} (kopija)"
        return self.save_garden(self.new_garden_id(), {**source, "name": copy_name})

    def rename_garden(self, garden_id: str, name: str) -> dict[str, Any]:
        garden = self.garden(garden_id)
        if garden is None:
            raise LookupError("sodas nerastas")
        return self.save_garden(garden_id, {**garden, "name": str(name)[:200]})

    def delete_garden(self, garden_id: str) -> None:
        path = self._garden_path(garden_id)
        if path.exists():
            path.unlink()

    def gardens(self) -> list[dict[str, Any]]:
        out = []
        for path in (self.root / "gardens").glob("*.json"):
            g = self._read(path)
            if not isinstance(g, dict) or self._is_blank(g):
                continue
            out.append({"id": g.get("id", path.stem), "name": g.get("name") or path.stem, "updated_at": g.get("updated_at"),
                        "nodes": len(g.get("nodes") or [])})
        return sorted(out, key=lambda g: g.get("updated_at") or "", reverse=True)

    # -- a garden as a file (to share it: ⬇ downloaded by one, ⬆ uploaded by another) -------------------------
    def garden_file(self, garden_id: str) -> dict[str, Any]:
        """The garden as it may be shared: its nodes, relationships, view and the datasets it used."""
        g = self.garden(garden_id)
        if g is None:
            raise LookupError("sodas nerastas – pirmiausia jame ką nors pasodinkite")
        body = {k: copy.deepcopy(g[k]) for k in GARDEN_KEYS if k in g}
        return {"format": GARDEN_FILE, "program": "Sodas", "exported_at": _now(), "id": garden_id,
                "garden": body, "sources": sekimas.clean_sources(g.get("sources"))}

    def import_garden(self, file: Any, name: str | None = None) -> dict[str, Any]:
        """A garden file becomes a new garden; the datasets it used come with it."""
        if not isinstance(file, dict) or file.get("format") != GARDEN_FILE or not isinstance(file.get("garden"), dict):
            raise ValueError("tai ne Sodo byla (laukiama „sodo-byla/1“)")
        g = file["garden"]
        if not isinstance(g.get("nodes") or [], list) or not isinstance(g.get("edges") or [], list):
            raise ValueError("Sodo byla sugadinta: mazgai ir ryšiai turi būti sąrašai.")
        nodes = [n for n in g.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("data"), dict) and n["data"].get("id")]
        ids = {str(n["data"]["id"]) for n in nodes}
        edges = [e for e in g.get("edges") or [] if isinstance(e, dict) and isinstance(e.get("data"), dict)
                 and e["data"].get("source") in ids and e["data"].get("target") in ids]
        if not nodes:
            raise ValueError("Sodo byloje nėra mazgų.")
        nodes = copy.deepcopy(nodes)
        for n in nodes:
            pic = n["data"].get("avatar")
            if pic is not None and not str(pic).startswith("/sodas-img/"):
                n["data"].pop("avatar")       # a picture from elsewhere would tell that site who opened the garden
        value = {k: copy.deepcopy(g[k]) for k in GARDEN_KEYS if k in g and k not in ("nodes", "edges")}
        value.update(nodes=nodes, edges=edges, name=str(name or g.get("name") or "Įkeltas sodas").strip()[:200] or "Įkeltas sodas",
                     sources=file.get("sources"))
        value["basket"] = [b for b in value.get("basket") or [] if b in ids] if isinstance(value.get("basket"), list) else []
        new_id = self.new_garden_id()
        out = self.save_garden(new_id, value)
        return {**out, "id": new_id, "name": value["name"], "nodes": len(nodes)}

    # -- drafts: unsaved work of a page (the workshop's canvas) ---------------------------
    def draft(self, kind: str) -> dict[str, Any] | None:
        if kind not in DRAFT_KINDS:
            raise ValueError("nežinomas juodraštis")
        d = self._read(self.root / "juodrasciai.json", {}).get(kind)
        return copy.deepcopy(d) if d else None

    def save_draft(self, kind: str, data: Any) -> dict[str, Any]:
        if kind not in DRAFT_KINDS:
            raise ValueError("nežinomas juodraštis")
        if len(json.dumps(data, ensure_ascii=False)) > MAX_DRAFT_BYTES:
            raise ValueError("juodraštis per didelis")
        entry = {"data": copy.deepcopy(data), "at": _now()} if data is not None else None
        drafts = self._read(self.root / "juodrasciai.json", {})
        if entry is None:
            drafts.pop(kind, None)
        else:
            drafts[kind] = entry
        self._write(self.root / "juodrasciai.json", drafts)
        return {"saved": entry is not None, "at": entry["at"] if entry else None}

    # -- images ---------------------------------------------------------------------
    def save_image(self, filename: str, data: bytes) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_TYPES:
            raise ValueError(f"leidžiami formatai: {', '.join(sorted(IMAGE_TYPES))}")
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("paveiksliukas tuščias arba didesnis nei 2 MB")
        if ext == ".svg" and b"<svg" not in data[:4096].lower():
            raise ValueError("SVG byla neatpažinta")
        name = hashlib.sha256(data).hexdigest()[:24] + ext
        path = self.root / "images" / name
        if not path.exists():
            path.write_bytes(data)
        return f"/sodas-img/{name}"

    def image(self, name: str) -> tuple[bytes, str] | None:
        if not re.match(r"^[0-9a-f]{24}\.[a-z]{3,4}$", name):
            return None
        path = self.root / "images" / name
        ext = path.suffix.lower()
        if ext not in IMAGE_TYPES or not path.exists():
            return None
        return path.read_bytes(), IMAGE_TYPES[ext]

    # -- log ------------------------------------------------------------------------
    def log(self, level: str, source: str, message: str, detail: Any = None) -> dict[str, Any]:
        entry = {"at": _now(), "level": level if level in {"error", "warning", "info"} else "info",
                 "source": str(source)[:40], "message": str(message)[:2000]}
        if detail not in (None, ""):
            entry["detail"] = str(detail)[:8000]
        with self.lock:
            self._log.append(entry)
            with (self.root / "zurnalas.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def log_entries(self) -> list[dict[str, Any]]:
        return list(reversed(self._log))

    def clear_log(self) -> None:
        with self.lock:
            self._log.clear()
            (self.root / "zurnalas.jsonl").write_text("", encoding="utf-8")
