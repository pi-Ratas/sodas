from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def verify_emit(out_dir: Path) -> dict[str, Any]:
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "error", "errors": ["manifest.json missing"], "counts": {}}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = {"batches": len(manifest.get("batches", [])), "rows": 0, "diagnostics": len(manifest.get("diagnostics", []))}
    errors = []
    samples = []
    for batch in manifest.get("batches", []):
        cyp = out_dir / batch["cypher"]
        params = out_dir / batch["params"]
        if not cyp.exists():
            errors.append(f"missing cypher: {batch['cypher']}")
        if not params.exists():
            errors.append(f"missing params: {batch['params']}")
            continue
        with params.open("r", encoding="utf-8", newline="") as fh:
            lines = [ln for ln in fh if ln.strip()]
        counts["rows"] += len(lines)
        if len(lines) != batch["rows"]:
            errors.append(f"row count mismatch in {batch['params']}: manifest={batch['rows']} actual={len(lines)}")
        for line in lines[:3]:
            obj = json.loads(line)
            if "key" in obj and not obj["key"]:
                errors.append(f"empty key in {batch['params']}")
            if "props" in obj and "provenance" in obj["props"]:
                errors.append(f"forbidden provenance property in {batch['params']}")
            if batch.get("kind") == "relationship" and not obj.get("props", {}).get("key"):
                errors.append(f"relationship key missing in {batch['params']}")
            samples.append(obj.get("key") or obj.get("start_key"))
    diagnostics = manifest.get("diagnostics", [])
    hard = [d for d in diagnostics if d.get("severity") == "error"]
    if hard:
        errors.append(f"{len(hard)} error diagnostic(s) present")
    status = "ok" if not errors else "error"
    return {"status": status, "errors": errors[:20], "counts": counts, "sample_keys": samples[:10]}
