from __future__ import annotations

import csv
import configparser
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterable, Iterator


# Released CLDF tables may contain long, quoted evidence fields.
csv.field_size_limit(64 * 1024 * 1024)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


NORMALIZATION_RULE = "nfkc-casefold-space"
NORMALIZATION_VERSION = "1.1.0"


def normalize_search_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def normalize_no_marks(value: Any) -> str | None:
    text = normalize_search_text(value)
    if text in (None, ""):
        return text
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_ascii(value: Any) -> str | None:
    text = normalize_no_marks(value)
    if text in (None, ""):
        return text
    return text.encode("ascii", "ignore").decode("ascii") or None


def search_props(display_name: Any, *alternates: Any) -> dict[str, Any]:
    tokens = []
    for value in (display_name, *alternates):
        for variant in (normalize_search_text(value), normalize_no_marks(value), normalize_ascii(value)):
            if variant and variant not in tokens:
                tokens.append(variant)
    props: dict[str, Any] = {
        "display_name": str(display_name) if display_name not in (None, "") else None,
        "search_text": normalize_search_text(display_name),
        "search_no_marks": normalize_no_marks(display_name),
        "search_ascii": normalize_ascii(display_name),
        "search_tokens": tokens or None,
        "normalization_rule": NORMALIZATION_RULE,
        "normalization_version": NORMALIZATION_VERSION,
    }
    return {k: v for k, v in props.items() if v is not None}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def escape_key_part(value: Any) -> str:
    return str(value).replace("%", "%25").replace("/", "%2F").replace("|", "%7C")


def iter_data_file(path: Path) -> Iterator[str]:
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            yield from fh
        return
    zip_path = path.with_suffix(path.suffix + ".zip")
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            name = path.name
            if name not in zf.namelist():
                matches = [n for n in zf.namelist() if Path(n).name == path.name]
                if not matches:
                    raise FileNotFoundError(path)
                name = matches[0]
            with zf.open(name) as fh:
                yield from io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
        return
    raise FileNotFoundError(path)


def csv_dialect_for(path: Path, dialect: dict[str, Any] | None = None) -> dict[str, Any]:
    dialect = dialect or {}
    delim = dialect.get("delimiter")
    if delim is None:
        delim = "\t" if path.suffix.lower() == ".tsv" else ","
    return {
        "delimiter": delim,
        "quotechar": dialect.get("quoteChar", '"'),
        "doublequote": True,
        "skipinitialspace": bool(dialect.get("skipInitialSpace", False)),
    }


def column_map(columns: Iterable[Any]) -> dict[str, Any]:
    return {c.name: c for c in columns}


def apply_null(value: str, nulls: Iterable[str] | None = None) -> str | None:
    null_set = {str(v) for v in (nulls or [])}
    if value in null_set:
        return None
    return value


def value_for_column(row: dict[str, str], column: Any, split: bool = False) -> Any:
    value = apply_null(row.get(column.name, ""), getattr(column, "null", []))
    if value is None:
        return None
    sep = getattr(column, "separator", None)
    if split and sep:
        return [part for part in value.split(sep) if apply_null(part, getattr(column, "null", [])) not in (None, "")]
    return value


def dict_rows(path: Path, dialect: dict[str, Any] | None = None) -> Iterator[tuple[int, dict[str, str]]]:
    if (dialect or {}).get("adapter") == "glottolog_ini_tree":
        for offset, source in enumerate(sorted(path.rglob("md.ini")), start=2):
            raw = source.read_text(encoding="utf-8-sig")
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read_string(raw)
            core = config["core"]
            parent = source.parent.parent.name
            yield offset, {
                "ID": source.parent.name,
                "Name": core.get("name", ""),
                "Level": core.get("level", ""),
                "Parent": parent if parent != "tree" else "",
                "ISO639P3code": core.get("iso639-3", ""),
                "Latitude": core.get("latitude", ""),
                "Longitude": core.get("longitude", ""),
                "_source_file": source.relative_to(path.parent.parent).as_posix(),
                "_raw_ini": raw,
            }
        return
    reader = csv.DictReader(iter_data_file(path), **csv_dialect_for(path, dialect))
    for offset, row in enumerate(reader, start=2):
        yield offset, {k: (v if v is not None else "") for k, v in row.items()}


def count_rows(path: Path, dialect: dict[str, Any] | None = None) -> int:
    return sum(1 for _ in dict_rows(path, dialect))


def file_manifest(paths: Iterable[Path], root: Path) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for path in sorted({p for p in paths}, key=lambda p: p.as_posix()):
        candidates = [path]
        if not path.exists():
            candidates.append(path.with_suffix(path.suffix + ".zip"))
        real = next((p for p in candidates if p.exists() and p.is_file()), None)
        if real is None or real in seen:
            continue
        seen.add(real)
        data = real.read_bytes()
        out.append({"path": relpath(real, root), "sha256": sha256_bytes(data), "bytes": len(data)})
    return out
