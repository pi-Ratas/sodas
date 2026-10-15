from __future__ import annotations

import csv
import glob
from dataclasses import replace
from pathlib import Path
from typing import Any

from .model import CLDF, ColumnInfo, Diagnostic, FileInventory, ForeignKeyInfo, InspectResult, ManifestEntry, TableInfo
from .profiles import Profile
from .util import count_rows, file_manifest, read_json, relpath


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _metadata_paths(root: Path, profile: Profile) -> list[Path]:
    globs = _as_list(profile.input.get("metadata_glob"))
    out: list[Path] = []
    for pattern in globs:
        out.extend(Path(p) for p in glob.glob(str(root / pattern), recursive=True))
    return list(dict.fromkeys(p for p in out if p.is_file()))


def _extra_paths(root: Path, profile: Profile) -> list[Path]:
    out: list[Path] = []
    for pattern in _as_list(profile.input.get("extra_files")):
        out.extend(Path(p) for p in glob.glob(str(root / pattern), recursive=True))
    return sorted({p for p in out if p.is_file()})


def _column(col: dict[str, Any]) -> ColumnInfo:
    return ColumnInfo(
        name=col.get("name", ""),
        property_url=col.get("propertyUrl"),
        separator=col.get("separator"),
        null=[str(v) for v in _as_list(col.get("null"))],
        datatype=col.get("datatype"),
    )


def _fk(raw: dict[str, Any]) -> ForeignKeyInfo:
    ref = raw.get("reference", {})
    return ForeignKeyInfo(
        columns=tuple(_as_list(raw.get("columnReference"))),
        reference_resource=ref.get("resource", ""),
        reference_columns=tuple(_as_list(ref.get("columnReference"))),
    )


def _table_from_metadata(root: Path, metadata_path: Path, raw_table: dict[str, Any], inherited_dialect: dict[str, Any], known_row_counts: dict[str, int] | None = None, fast: bool = False) -> TableInfo:
    schema = raw_table.get("tableSchema", {})
    url = raw_table.get("url", "")
    path = (metadata_path.parent / url).resolve()
    dialect = dict(inherited_dialect)
    dialect.update(raw_table.get("dialect", {}))
    columns = [_column(c) for c in schema.get("columns", [])]
    pk = tuple(_as_list(schema.get("primaryKey")))
    fks = [_fk(f) for f in schema.get("foreignKeys", [])]
    role = raw_table.get("dc:conformsTo") or raw_table.get("propertyUrl") or raw_table.get("aboutUrl") or "generic"
    relative_path = relpath(path, root)
    if known_row_counts is not None and relative_path in known_row_counts:
        rows = known_row_counts[relative_path]
    else:
        rows = -1 if fast else count_rows(path, dialect)
    return TableInfo(
        path=path,
        url=url,
        role=role,
        dialect=dialect,
        columns=columns,
        primary_key=pk,
        foreign_keys=fks,
        row_count=rows,
        source_metadata=relpath(metadata_path, root),
        interpretation="source_records",
    )


def inspect_dataset(dataset_id: str, root: Path, profile: Profile, known_row_counts: dict[str, int] | None = None,
                    known_manifest: list[dict[str, Any]] | None = None, fast: bool = False) -> InspectResult:
    """``fast=True`` skips row counting and file hashing (row_count=-1, empty manifest); for previews only."""
    if fast and known_manifest is None:
        known_manifest = []
    diagnostics: list[Diagnostic] = []
    if not root.exists():
        return InspectResult(dataset_id, root, profile.source_path, "missing", profile.verified, [], [], [], [], [], [], [
            Diagnostic("error", "PATH_MISSING", f"path does not exist: {root}")
        ])
    metadata_paths = _metadata_paths(root, profile)
    if profile.input.get("kind") == "cldf" and profile.input.get("require_metadata", True) and not metadata_paths:
        diagnostics.append(Diagnostic("error", "NO_METADATA", "no CLDF/CSVW metadata matched profile"))
    if profile.input.get("require_exactly_one_metadata") and len(metadata_paths) != 1:
        diagnostics.append(Diagnostic("error", "METADATA_COUNT", f"expected exactly one metadata file, found {len(metadata_paths)}"))

    table_roles = profile.input.get("table_roles", {}) or {}
    tables: list[TableInfo] = []
    data_files: list[Path] = []
    processed_files: set[str] = set()
    citation_files: list[str] = []
    seen_table_paths: set[Path] = set()
    for meta in metadata_paths:
        try:
            raw = read_json(meta)
        except Exception as exc:
            diagnostics.append(Diagnostic("error", "BAD_METADATA_JSON", f"{relpath(meta, root)}: {exc}"))
            continue
        inherited_dialect = raw.get("dialect", {})
        for src in _as_list(raw.get("dc:source")):
            bib = (meta.parent / str(src)).resolve()
            if bib.exists():
                citation_files.append(relpath(bib, root))
                data_files.append(bib)
                processed_files.add(relpath(bib, root))
        for raw_table in raw.get("tables", []):
            try:
                table = _table_from_metadata(root, meta, raw_table, inherited_dialect, known_row_counts, fast)
            except Exception as exc:
                diagnostics.append(Diagnostic("error", "READ_TABLE_FAILED", f"{raw_table.get('url', '')}: {exc}", table=raw_table.get("url")))
                continue
            if table.path in seen_table_paths:
                continue
            spec = table_roles.get(relpath(table.path, root)) or {}
            if spec.get("role") and table.role == "generic":
                # CSVW tables without dc:conformsTo (e.g. CLTS) get their role from the profile.
                table = replace(table, role=spec["role"])
            seen_table_paths.add(table.path)
            tables.append(table)
            data_files.append(table.path)
            processed_files.add(relpath(table.path if table.path.exists() else table.path.with_suffix(table.path.suffix + ".zip"), root))
            if not table.primary_key:
                diagnostics.append(Diagnostic("warning", "NO_PRIMARY_KEY", f"{table.url} has no declared primary key", table=table.url))
            if table.row_count == 0 or (table.row_count < 0 and not (table.path.exists() or table.path.with_suffix(table.path.suffix + ".zip").exists())):
                diagnostics.append(Diagnostic("warning", "EMPTY_OR_UNREADABLE_TABLE", f"{table.url} has zero readable rows", table=table.url))

    if profile.input.get("glottolog_tree"):
        tree = root / "languoids" / "tree"
        ini_files = sorted(tree.rglob("md.ini")) if tree.is_dir() else []
        if not ini_files:
            diagnostics.append(Diagnostic("error", "GLOTTOLOG_TREE_MISSING", "languoids/tree contains no md.ini files"))
        else:
            tables.append(TableInfo(
                tree, "languoids/tree/**/md.ini", CLDF + "LanguageTable",
                {"adapter": "glottolog_ini_tree"},
                [ColumnInfo("ID", CLDF + "id"), ColumnInfo("Name", CLDF + "name"),
                 ColumnInfo("Level", CLDF + "level"), ColumnInfo("Parent"),
                 ColumnInfo("ISO639P3code", CLDF + "iso639P3code"), ColumnInfo("Latitude", CLDF + "latitude"),
                 ColumnInfo("Longitude", CLDF + "longitude"),
                 ColumnInfo("_source_file"), ColumnInfo("_raw_ini")],
                ("ID",), [], len(ini_files), None,
            ))
            data_files.extend(ini_files)
            processed_files.update(relpath(p, root) for p in ini_files)

    for extra in _extra_paths(root, profile):
        suffix = extra.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            rel = relpath(extra, root)
            spec = table_roles.get(rel) or {}
            try:
                rows = -1 if fast else count_rows(extra, {"delimiter": delimiter})
            except Exception:
                rows = 0
            try:
                with extra.open("r", encoding="utf-8-sig", newline="") as fh:
                    header = next(csv.reader(fh, delimiter=delimiter), [])
            except Exception:
                header = []
            columns = [ColumnInfo(name) for name in header]
            pk = tuple(_as_list(spec.get("primary_key"))) if all(k in header for k in _as_list(spec.get("primary_key"))) else tuple()
            tables.append(TableInfo(extra.resolve(), rel, spec.get("role", "extra"), {"delimiter": delimiter}, columns, pk, [], rows, None))
            processed_files.add(relpath(extra, root))
        data_files.append(extra)
        if suffix == ".bib":
            citation_files.append(relpath(extra, root))

    for pattern in ("LICENSE*", "COPYING*", "CITATION*"):
        data_files.extend(Path(p) for p in glob.glob(str(root / pattern)))
    license_files = [relpath(p, root) for p in data_files if p.name.upper().startswith(("LICENSE", "COPYING")) and p.exists()]
    for p in data_files:
        if p.exists() and (p.name.upper().startswith(("LICENSE", "COPYING", "CITATION")) or p.suffix.lower() == ".bib"):
            processed_files.add(relpath(p, root))

    likely_ext = {".csv", ".tsv", ".bib", ".json", ".sqlite", ".gml", ".geojson", ".ini", ".zip"}
    file_inventory: list[FileInventory] = []
    for path in sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in likely_ext), key=lambda p: relpath(p, root)):
        rp = relpath(path, root)
        if ".git/" in rp or "/.git/" in rp:
            continue
        if rp in processed_files:
            status = "processed"
            reason = "declared by metadata/profile or supporting citation/license file"
        elif any(rp == m for m in [relpath(p, root) for p in metadata_paths]):
            status = "processed"
            reason = "metadata file"
        elif path.suffix.lower() in {".csv", ".tsv"}:
            status = "not_included"
            reason = "possible tabular data not declared by selected profile"
        elif path.suffix.lower() in {".sqlite", ".gml", ".geojson", ".zip"}:
            status = "not_included"
            reason = "binary or derived artefact retained out of row importer unless profile declares it"
        else:
            status = "not_included"
            reason = "not declared by selected profile"
        file_inventory.append(FileInventory(rp, status, reason))

    manifest_dicts = known_manifest if known_manifest is not None else file_manifest([*metadata_paths, *data_files], root)
    manifest = [ManifestEntry(**m) for m in manifest_dicts]
    status = "ok" if not any(d.severity == "error" for d in diagnostics) else "errors"
    if not profile.verified:
        diagnostics.append(Diagnostic("warning", "PROFILE_UNVERIFIED", "profile is marked unverified; apply requires --allow-unverified-profile"))
    return InspectResult(
        dataset_id=dataset_id,
        path=root,
        profile_path=profile.source_path,
        status=status,
        profile_verified=profile.verified,
        metadata_files=[relpath(p, root) for p in metadata_paths],
        tables=tables,
        manifest=manifest,
        license_files=sorted(set(license_files)),
        citation_files=sorted(set(citation_files)),
        file_inventory=file_inventory,
        diagnostics=diagnostics,
    )
