from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from .inspect import inspect_dataset
from .model import CONTRACT_VERSION, Diagnostic, GraphRow, ImportPlan, RelRow, TableInfo
from .profiles import Profile
from .semantics import DatasetContext, build_context, role_name, rule_sha_for, semantic_for_record
from .util import canonical_json, column_map, dict_rows, escape_key_part, sha256_text, value_for_column


def manifest_sha(manifest: list[Any]) -> str:
    return sha256_text(canonical_json([getattr(m, "__dict__", m) for m in manifest]))


def release_key(dataset_id: str, manifest: list[Any]) -> tuple[str, str]:
    msha = manifest_sha(manifest)
    return f"{dataset_id}@{msha}", msha


def table_key(release: str, table: TableInfo) -> str:
    scope = table.source_metadata or ""
    return f"{release}/table/{escape_key_part(scope)}/{escape_key_part(table.url)}"


def table_identity(table: TableInfo) -> tuple[str | None, str]:
    return table.source_metadata, table.url


def record_local_id(table: TableInfo, row_number: int, row: dict[str, Any]) -> tuple[str, bool]:
    cols = column_map(table.columns)
    if table.primary_key and all(k in cols and value_for_column(row, cols[k]) not in (None, "") for k in table.primary_key):
        return "|".join(escape_key_part(value_for_column(row, cols[k])) for k in table.primary_key), False
    return f"{table.url}#{row_number}", True


def record_key(release: str, table: TableInfo, row_number: int, row: dict[str, Any]) -> tuple[str, str, bool]:
    local_id, unstable = record_local_id(table, row_number, row)
    scope = table.source_metadata or ""
    return f"{release}/table/{escape_key_part(scope)}/{escape_key_part(table.url)}/record/{local_id}", local_id, unstable


def add_node(nodes: dict[str, list[GraphRow]], node_label: str, key: str, **props: Any) -> None:
    nodes[node_label].append(GraphRow(node_label, key, {"key": key, **{k: v for k, v in props.items() if v is not None}}))


def run_key_for(release: str, config_sha256: str) -> str:
    return "run:" + str(uuid.uuid5(uuid.NAMESPACE_URL, release + config_sha256))


def context_for(dataset_id: str, release: str, profile: Profile, tables: list[TableInfo]) -> DatasetContext:
    return build_context(dataset_id, release, rule_sha_for(dataset_id, profile), profile.semantics, tables, record_key)


def _fk_value_tuples(table: TableInfo, row: dict[str, str], columns: tuple[str, ...]) -> list[tuple[str, ...]]:
    cmap = column_map(table.columns)
    values: list[list[str]] = []
    for name in columns:
        col = cmap.get(name)
        if col is None:
            return []
        value = value_for_column(row, col, split=True)
        if value in (None, ""):
            return []
        values.append(value if isinstance(value, list) else [value])
    lengths = {len(v) for v in values}
    if lengths == {1}:
        return [tuple(v[0] for v in values)]
    if len(lengths) == 1:
        return [tuple(v[i] for v in values) for i in range(next(iter(lengths)))]
    # Ambiguous CSVW shape: generate the conservative product for diagnostics/resolution.
    out = [()]
    for vals in values:
        out = [prefix + (v,) for prefix in out for v in vals]
    return out


def _target_table(source: TableInfo, tables: list[TableInfo], resource: str) -> TableInfo | None:
    for table in tables:
        if table.url == resource and table.source_metadata == source.source_metadata:
            return table
    for table in tables:
        if table.url == resource:
            return table
    return None


def _is_external_fk_resource(resource: str) -> bool:
    return "://" in resource or resource.startswith(("../", "/", "file:"))


def build_plan(dataset_id: str, root: Path, profile: Profile, strict: bool = True) -> ImportPlan:
    ins = inspect_dataset(dataset_id, root, profile)
    release, msha = release_key(dataset_id, ins.manifest)
    rule_sha = rule_sha_for(dataset_id, profile)
    ctx = context_for(dataset_id, release, profile, ins.tables)
    nodes: dict[str, list[GraphRow]] = defaultdict(list)
    rels: list[RelRow] = []
    diagnostics = list(ins.diagnostics) + ctx.diagnostics
    add_node(nodes, "Dataset", dataset_id, title=profile.raw.get("title") or dataset_id)
    add_node(nodes, "DatasetRelease", release, version_label=profile.raw.get("version_label"), manifest_sha256=msha)
    run_key = run_key_for(release, profile.config_sha256)
    add_node(nodes, "ImportRun", run_key, started_at=None, status="planned", profile_version=profile.profile_version, config_sha256=profile.config_sha256, rule_sha256=rule_sha, contract_version=CONTRACT_VERSION)
    rels.append(RelRow("DatasetRelease", release, "RELEASE_OF", "Dataset", dataset_id, {}))
    rels.append(RelRow("ImportRun", run_key, "IMPORTS", "DatasetRelease", release, {}))
    rows_by_table: dict[tuple[str | None, str], list[tuple[int, dict[str, str], str]]] = {}
    indexes: dict[tuple[tuple[str | None, str], tuple[str, ...]], dict[tuple[str, ...], list[str]]] = defaultdict(lambda: defaultdict(list))
    external_fk_warned: set[tuple[str | None, str, tuple[str, ...], str]] = set()
    for table in ins.tables:
        tkey = table_key(release, table)
        schema = {
            "columns": [c.__dict__ for c in table.columns],
            "primary_key": list(table.primary_key),
            "foreign_keys": [f.__dict__ for f in table.foreign_keys],
            "dialect": table.dialect,
        }
        add_node(nodes, "SourceTable", tkey, url=table.url, role=table.role, schema_json=canonical_json(schema), row_count=table.row_count)
        rels.append(RelRow("SourceTable", tkey, "IN_RELEASE", "DatasetRelease", release, {}))
        try:
            tid = table_identity(table)
            rows_by_table[tid] = []
            for rn, row in dict_rows(table.path, table.dialect):
                rkey, local_id, unstable = record_key(release, table, rn, row)
                raw_json = canonical_json(row)
                add_node(nodes, "SourceRecord", rkey, local_id=local_id, row_sha256=sha256_text(raw_json), raw_json=raw_json, row_number=rn, unstable_key=unstable)
                rels.append(RelRow("SourceRecord", rkey, "IN_TABLE", "SourceTable", tkey, {}))
                rows_by_table[tid].append((rn, row, rkey))
                for cols in {table.primary_key, *[fk.reference_columns for fk in table.foreign_keys if fk.reference_resource == table.url]}:
                    if cols:
                        for vals in _fk_value_tuples(table, row, cols):
                            indexes[(tid, cols)][vals].append(rkey)
                semantic_for_record(ctx, table, rn, row, rkey, nodes, rels)
        except Exception as exc:
            diagnostics.append(Diagnostic("error", "READ_TABLE_FAILED", f"{table.url}: {exc}", table=table.url))
    for table in ins.tables:
        for rn, row, rkey in rows_by_table.get(table_identity(table), []):
            for fk in table.foreign_keys:
                target = _target_table(table, ins.tables, fk.reference_resource)
                vals_list = _fk_value_tuples(table, row, fk.columns)
                if not vals_list:
                    continue
                if target is None:
                    if _is_external_fk_resource(fk.reference_resource):
                        warn_key = (*table_identity(table), fk.columns, fk.reference_resource)
                        if warn_key not in external_fk_warned:
                            diagnostics.append(Diagnostic("warning", "FK_EXTERNAL_RESOURCE", f"{table.url} references external resource {fk.reference_resource}", table=table.url, sample={"columns": fk.columns}))
                            external_fk_warned.add(warn_key)
                        continue
                    diagnostics.append(Diagnostic("error", "FK_TARGET_TABLE_MISSING", f"{table.url}:{rn} references missing table {fk.reference_resource}", rkey, table.url, {"columns": fk.columns}))
                    target_index = {}
                else:
                    target_tid = table_identity(target)
                    target_index = indexes.get((target_tid, fk.reference_columns), {})
                    if not target_index:
                        # Build index for non-PK referenced columns.
                        target_index = defaultdict(list)
                        for _, target_row, target_key in rows_by_table.get(target_tid, []):
                            for vals in _fk_value_tuples(target, target_row, fk.reference_columns):
                                target_index[vals].append(target_key)
                        indexes[(target_tid, fk.reference_columns)] = target_index
                for vals in vals_list:
                    hits = list(target_index.get(vals, []))
                    if len(hits) == 1:
                        rels.append(RelRow("SourceRecord", rkey, "REFERS_TO_RECORD", "SourceRecord", hits[0], {"columns": ",".join(fk.columns)}))
                    else:
                        status = "missing" if len(hits) == 0 else "ambiguous"
                        code = "FK_NOT_FOUND" if status == "missing" else "FK_AMBIGUOUS"
                        diagnostics.append(Diagnostic("error", code, f"{table.url}:{rn} unresolved FK {fk.columns}={vals} -> {fk.reference_resource}.{fk.reference_columns}", rkey, table.url, {"values": vals, "matches": len(hits)}))
                        rrkey = "rawref:" + sha256_text(f"{rkey}|{','.join(fk.columns)}|{vals}|{fk.reference_resource}|{status}")
                        add_node(nodes, "RawReference", rrkey, column=",".join(fk.columns), target_raw="|".join(vals), resolution_status=status)
                        rels.append(RelRow("RawReference", rrkey, "FROM_RECORD", "SourceRecord", rkey, {}))
    assertions = len(nodes.get("Assertion", []))
    deferred = len(nodes.get("RawReference", []))
    if strict and any(d.severity == "error" for d in diagnostics):
        diagnostics.append(Diagnostic("error", "STRICT_BLOCK", "strict mode blocks apply/emit until errors are fixed"))
    return ImportPlan(ins, release, msha, profile.config_sha256, rule_sha, dict(nodes), rels, diagnostics, deferred, assertions, 0)
