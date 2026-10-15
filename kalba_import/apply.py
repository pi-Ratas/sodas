from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def apply_emit(out_dir: Path, uri: str, user: str, password: str, database: str = "neo4j") -> dict[str, Any]:
    try:
        from neo4j import GraphDatabase
    except ModuleNotFoundError as exc:
        raise RuntimeError("official neo4j Python driver is not installed; install with: python3 -m pip install 'neo4j>=5'") from exc
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    applied = 0
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            constraints = (out_dir / "constraints.cypher").read_text(encoding="utf-8")
            for statement in [s.strip() for s in constraints.split(";") if s.strip()]:
                session.execute_write(lambda tx, q: tx.run(q).consume(), statement)
            for batch in manifest.get("batches", []):
                query = (out_dir / batch["cypher"]).read_text(encoding="utf-8")
                rows = _read_ndjson(out_dir / batch["params"])
                session.execute_write(lambda tx, q, r: tx.run(q, rows=r).consume(), query, rows)
                applied += len(rows)
    return {"status": "ok", "rows": applied, "release_key": manifest.get("release_key")}
