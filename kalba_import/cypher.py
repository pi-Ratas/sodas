from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import GraphRow, ImportPlan, RelRow
from .util import canonical_json, sha256_text


CONSTRAINT_LABELS = [
    "Dataset", "DatasetRelease", "ImportRun", "SourceTable", "SourceRecord", "Source",
    "Citation", "RawReference", "Assertion", "ExternalIdentifier", "IdentityCandidate",
    "Languoid", "Society", "Lexeme", "Form", "Sense", "Concept", "CognateSet",
    "ProtoForm", "Sound", "Phoneme", "Feature", "FeatureValue", "Text", "Attestation",
    "TimeSpan", "Inventory", "Measure", "Measurement", "CollectionMembership", "Evidence",
    "BorrowingEvent", "Grapheme", "TranscriptionSystem",
]


SEARCH_INDEX_LABELS = [
    "Form", "Lexeme", "Sense", "Concept", "Languoid", "CognateSet", "ProtoForm", "Society", "Feature", "FeatureValue",
    "Sound", "Grapheme", "TranscriptionSystem",
]
SEARCH_INDEX_PROPERTIES = ["display_name", "search_text", "search_ascii"]
# properties the program looks nodes up by (Vaiva, flags, LKEŽDB plans): (label, property)
LOOKUP_INDEXES = [
    ("ExternalIdentifier", "scheme"), ("ExternalIdentifier", "value"), ("Languoid", "glottocode"),
    ("Concept", "concepticon_id"), ("Concept", "concepticon_gloss"), ("Concept", "dataset"),
    ("Sound", "symbol"), ("Grapheme", "symbol"),
]


def lookup_index_cypher() -> list[str]:
    return [f"CREATE RANGE INDEX kalba_{label.lower()}_{prop} IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
            for label, prop in LOOKUP_INDEXES]


def _safe_name(name: str) -> str:
    if not name.replace("_", "").isalnum() or not name[0].isalpha():
        raise ValueError(f"unsafe Cypher name: {name!r}")
    return name


def constraint_cypher() -> str:
    parts = []
    for label in CONSTRAINT_LABELS:
        name = "kalba_" + label.lower() + "_key"
        parts.append(f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:{label}) REQUIRE n.key IS UNIQUE;")
    for label in SEARCH_INDEX_LABELS:
        for prop in SEARCH_INDEX_PROPERTIES:
            parts.append(f"CREATE RANGE INDEX kalba_{label.lower()}_{prop} IF NOT EXISTS FOR (n:{label}) ON (n.{prop});")
    parts.extend(q + ";" for q in lookup_index_cypher())
    return "\n".join(parts) + "\n"


def node_cypher(label: str) -> str:
    label = _safe_name(label)
    return (
        "UNWIND $rows AS row\n"
        f"MERGE (n:{label} {{key: row.key}})\n"
        "SET n += row.props\n"
    )


def rel_cypher(rel_type: str, start_label: str, end_label: str) -> str:
    rel_type = _safe_name(rel_type)
    start_label = _safe_name(start_label)
    end_label = _safe_name(end_label)
    return (
        "UNWIND $rows AS row\n"
        f"MATCH (a:{start_label} {{key: row.start_key}})\n"
        f"MATCH (b:{end_label} {{key: row.end_key}})\n"
        f"MERGE (a)-[r:{rel_type} {{key: row.props.key}}]->(b)\n"
        "SET r += row.props\n"
    )


MAX_SOURCE_RECORD_KEYS = 50


def _dedupe_nodes(rows: list[GraphRow]) -> list[dict[str, Any]]:
    """Merge rows for one key: the first (owning) row's values win, record keys accumulate."""
    out: dict[str, dict[str, Any]] = {}
    record_keys: dict[str, set[str]] = {}
    for row in rows:
        props = {k: v for k, v in row.props.items() if v is not None and k != "key"}
        current = out.setdefault(row.key, {"key": row.key, "props": {}})
        record_keys.setdefault(row.key, set()).update(_record_keys(props))
        props.pop("source_record_key", None)
        props.pop("source_record_keys", None)
        for k, v in props.items():
            current["props"].setdefault(k, v)
    for key, current in out.items():
        merged = sorted(record_keys[key])
        if len(merged) > MAX_SOURCE_RECORD_KEYS:
            current["props"]["source_record_count"] = len(merged)
            merged = merged[:MAX_SOURCE_RECORD_KEYS]
        if len(merged) > 1:
            current["props"]["source_record_keys"] = merged
        elif merged:
            current["props"]["source_record_key"] = merged[0]
    return [out[k] for k in sorted(out)]


def _record_keys(props: dict[str, Any]) -> set[str]:
    keys = set()
    if props.get("source_record_key"):
        keys.add(str(props["source_record_key"]))
    for key in props.get("source_record_keys") or []:
        keys.add(str(key))
    return keys


def _rel_key(row: RelRow) -> str:
    raw = {
        "start_label": row.start_label,
        "start_key": row.start_key,
        "rel_type": row.rel_type,
        "end_label": row.end_label,
        "end_key": row.end_key,
        "props": {k: v for k, v in row.props.items() if k != "key"},
    }
    return "rel:" + sha256_text(canonical_json(raw))


def _dedupe_rels(rows: list[RelRow]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        props = dict(row.props)
        props["key"] = props.get("key") or _rel_key(row)
        out[props["key"]] = {"start_key": row.start_key, "end_key": row.end_key, "props": props}
    return [out[k] for k in sorted(out)]


def emit(plan: ImportPlan, out_dir: Path, batch_size: int = 1000) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "constraints.cypher").write_text(constraint_cypher(), encoding="utf-8")
    manifest: dict[str, Any] = {
        "dataset_id": plan.inspect.dataset_id,
        "release_key": plan.release_key,
        "manifest_sha256": plan.manifest_sha256,
        "batches": [],
        "diagnostics": [d.__dict__ for d in plan.diagnostics],
    }
    for label, rows in sorted(plan.nodes.items()):
        data = _dedupe_nodes(rows)
        if not data:
            continue
        cypher_name = f"node_{label}.cypher"
        (out_dir / cypher_name).write_text(node_cypher(label), encoding="utf-8")
        for i in range(0, len(data), batch_size):
            chunk = data[i:i + batch_size]
            ndjson = f"node_{label}_{i // batch_size:04d}.ndjson"
            (out_dir / ndjson).write_text("\n".join(canonical_json(r) for r in chunk) + "\n", encoding="utf-8")
            manifest["batches"].append({"kind": "node", "label": label, "cypher": cypher_name, "params": ndjson, "rows": len(chunk)})
    grouped: dict[tuple[str, str, str], list[RelRow]] = {}
    for row in plan.relationships:
        grouped.setdefault((row.rel_type, row.start_label, row.end_label), []).append(row)
    for (rel_type, start_label, end_label), rows in sorted(grouped.items()):
        data = _dedupe_rels(rows)
        cypher_name = f"rel_{start_label}_{rel_type}_{end_label}.cypher"
        (out_dir / cypher_name).write_text(rel_cypher(rel_type, start_label, end_label), encoding="utf-8")
        for i in range(0, len(data), batch_size):
            chunk = data[i:i + batch_size]
            ndjson = f"rel_{start_label}_{rel_type}_{end_label}_{i // batch_size:04d}.ndjson"
            (out_dir / ndjson).write_text("\n".join(canonical_json(r) for r in chunk) + "\n", encoding="utf-8")
            manifest["batches"].append({"kind": "relationship", "type": rel_type, "cypher": cypher_name, "params": ndjson, "rows": len(chunk), "start_label": start_label, "end_label": end_label})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
