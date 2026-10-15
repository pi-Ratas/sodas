from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cypher import node_cypher, rel_cypher
from .util import canonical_json, sha256_text


def add_identity_candidate(
    emit_dir: Path,
    left_label: str,
    left_key: str,
    right_label: str,
    right_key: str,
    reason: str,
    rule_id: str,
    status: str = "pending",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = emit_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ordered = sorted([(left_label, left_key), (right_label, right_key)], key=lambda x: (x[0], x[1]))
    candidate_key = "identity:" + sha256_text(canonical_json({"objects": ordered, "rule_id": rule_id}))
    evidence_key = "evidence:" + sha256_text(canonical_json({"candidate": candidate_key, "evidence": evidence or {}}))

    def rel_key(rel_type: str, start_label: str, start_key: str, end_label: str, end_key: str, props: dict[str, Any]) -> str:
        return "rel:" + sha256_text(canonical_json({
            "rel_type": rel_type,
            "start_label": start_label,
            "start_key": start_key,
            "end_label": end_label,
            "end_key": end_key,
            "props": {k: v for k, v in props.items() if k != "key"},
        }))

    def rel_row(rel_type: str, start_label: str, start_key: str, end_label: str, end_key: str, props: dict[str, Any] | None = None) -> dict[str, Any]:
        props = dict(props or {})
        props["key"] = props.get("key") or rel_key(rel_type, start_label, start_key, end_label, end_key, props)
        return {"start_key": start_key, "end_key": end_key, "props": props}

    additions = [
        ("node", "IdentityCandidate", node_cypher("IdentityCandidate"), f"candidate_{candidate_key[9:25]}.ndjson", [{"key": candidate_key, "props": {"reason": reason, "status": status, "rule_id": rule_id}}]),
        ("node", "Evidence", node_cypher("Evidence"), f"evidence_{evidence_key[9:25]}.ndjson", [{"key": evidence_key, "props": {"evidence_json": canonical_json(evidence or {})}}]),
        ("relationship", "CANDIDATE_LEFT", rel_cypher("CANDIDATE_LEFT", "IdentityCandidate", left_label), f"candidate_left_{candidate_key[9:25]}.ndjson", [rel_row("CANDIDATE_LEFT", "IdentityCandidate", candidate_key, left_label, left_key)]),
        ("relationship", "CANDIDATE_RIGHT", rel_cypher("CANDIDATE_RIGHT", "IdentityCandidate", right_label), f"candidate_right_{candidate_key[9:25]}.ndjson", [rel_row("CANDIDATE_RIGHT", "IdentityCandidate", candidate_key, right_label, right_key)]),
        ("relationship", "EVIDENCED_BY", rel_cypher("EVIDENCED_BY", "IdentityCandidate", "Evidence"), f"candidate_evidence_{candidate_key[9:25]}.ndjson", [rel_row("EVIDENCED_BY", "IdentityCandidate", candidate_key, "Evidence", evidence_key)]),
        ("relationship", "POSSIBLE_IDENTITY", rel_cypher("POSSIBLE_IDENTITY", left_label, right_label), f"possible_identity_{candidate_key[9:25]}.ndjson", [rel_row("POSSIBLE_IDENTITY", left_label, left_key, right_label, right_key, {"candidate_key": candidate_key, "rule_id": rule_id, "status": status})]),
    ]
    for kind, label_or_type, cypher, params, rows in additions:
        cypher_name = params.replace(".ndjson", ".cypher")
        (emit_dir / cypher_name).write_text(cypher, encoding="utf-8")
        (emit_dir / params).write_text("\n".join(canonical_json(row) for row in rows) + "\n", encoding="utf-8")
        entry = {"kind": kind, "cypher": cypher_name, "params": params, "rows": len(rows)}
        if kind == "node":
            entry["label"] = label_or_type
        else:
            entry["type"] = label_or_type
            if label_or_type == "POSSIBLE_IDENTITY":
                entry["start_label"] = left_label
                entry["end_label"] = right_label
            elif label_or_type == "EVIDENCED_BY":
                entry["start_label"] = "IdentityCandidate"
                entry["end_label"] = "Evidence"
            else:
                entry["start_label"] = "IdentityCandidate"
                entry["end_label"] = left_label if label_or_type.endswith("LEFT") else right_label
        manifest.setdefault("batches", []).append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"candidate_key": candidate_key, "evidence_key": evidence_key, "status": status}
