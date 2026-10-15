"""Operations that run directly against Neo4j: authority resolution, status, wipe."""
from __future__ import annotations

from typing import Any, Callable

from .semantics import AUTHORITY_SCHEMES


def _driver(uri: str, user: str, password: str):
    try:
        from neo4j import GraphDatabase
    except ModuleNotFoundError as exc:
        raise RuntimeError("official neo4j Python driver is not installed; install with: python3 -m pip install 'neo4j>=5'") from exc
    # Server notifications (e.g. "property key does not exist" before the first import) are noise here.
    return GraphDatabase.driver(uri, auth=(user, password), notifications_min_severity="OFF")


# Local object -> authority object sharing the same ExternalIdentifier.
# Society is not a Languoid (contract §6), so it gets ASSOCIATED_WITH instead of CORRESPONDS_TO.
_RESOLVE_QUERY = """
MATCH (e:ExternalIdentifier {{scheme: $scheme}})<-[:IDENTIFIED_BY]-(a:{auth_label} {{dataset: $authority}})
CALL (e, a) {{
  MATCH (n:{local_label})-[:IDENTIFIED_BY]->(e)
  WHERE n.dataset <> $authority
  MERGE (n)-[r:{rel_type} {{key: 'resolve:' + n.key + '|' + a.key}}]->(a)
  SET r.scheme = e.scheme, r.value = e.value, r.rule_id = 'authority-external-id-v1', r.status = 'resolved',
      r.dataset = n.dataset, r.dataset_release = n.dataset_release,
      r.source_record_key = coalesce(n.source_record_key, head(n.source_record_keys))
}} IN TRANSACTIONS OF 2000 ROWS
"""

_PENDING_QUERY = """
MATCH (e:ExternalIdentifier {scheme: $scheme})
WHERE NOT EXISTS { MATCH (e)<-[:IDENTIFIED_BY]-(a) WHERE a.dataset = $authority }
RETURN count(e) AS pending
"""


def resolve_neo4j(uri: str, user: str, password: str, database: str = "neo4j",
                  progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Idempotently link local objects to authority objects (contract §7 `resolve`)."""
    progress = progress or (lambda message: None)
    out: dict[str, Any] = {"status": "ok", "schemes": {}}
    with _driver(uri, user, password) as driver:
        with driver.session(database=database) as session:
            for scheme, (authority, auth_label, _prefix) in AUTHORITY_SCHEMES.items():
                pairs = [(auth_label, "CORRESPONDS_TO")]
                if auth_label == "Languoid":
                    pairs.append(("Society", "ASSOCIATED_WITH"))
                created = 0
                for local_label, rel_type in pairs:
                    progress(f"resolve: {scheme} {local_label}-[:{rel_type}]->{auth_label}")
                    query = _RESOLVE_QUERY.format(auth_label=auth_label, local_label=local_label, rel_type=rel_type)
                    summary = session.run(query, scheme=scheme, authority=authority).consume()
                    created += summary.counters.relationships_created
                pending = session.run(_PENDING_QUERY, scheme=scheme, authority=authority).single()["pending"]
                out["schemes"][scheme] = {"authority": authority, "relationships_created": created, "pending_identifiers": pending}
    return out


def neo4j_status(uri: str, user: str, password: str, database: str = "neo4j") -> dict[str, Any]:
    with _driver(uri, user, password) as driver:
        with driver.session(database=database) as session:
            datasets = session.run(
                "MATCH (d:Dataset) OPTIONAL MATCH (r:DatasetRelease)-[:RELEASE_OF]->(d) "
                "RETURN d.key AS dataset, collect(r.key) AS releases ORDER BY dataset").data()
            nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            schema = session.run("SHOW INDEXES YIELD type RETURN type, count(*) AS c").data()
            constraints = session.run("SHOW CONSTRAINTS YIELD name RETURN count(*) AS c").single()["c"]
    return {"ok": True, "datasets": datasets, "nodes": nodes, "indexes": {r["type"]: r["c"] for r in schema}, "constraints": constraints}


def wipe_neo4j(uri: str, user: str, password: str, database: str = "neo4j", *, include_lookup_indexes: bool = False,
               batch_size: int = 10000, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Delete every node, relationship, constraint and index of the database.

    Explicit administrative action (UI button with typed confirmation); the importer itself never deletes.
    LOOKUP (label/type token) indexes are Neo4j's built-in scan indexes and are kept unless asked.
    """
    progress = progress or (lambda message: None)
    result: dict[str, Any] = {"constraints_dropped": 0, "indexes_dropped": 0}
    with _driver(uri, user, password) as driver:
        with driver.session(database=database) as session:
            for record in session.run("SHOW CONSTRAINTS YIELD name RETURN name").data():
                session.run(f"DROP CONSTRAINT `{record['name'].replace('`', '``')}` IF EXISTS").consume()
                result["constraints_dropped"] += 1
            progress(f"wipe: dropped {result['constraints_dropped']} constraints")
            for record in session.run("SHOW INDEXES YIELD name, type RETURN name, type").data():
                if record["type"] == "LOOKUP" and not include_lookup_indexes:
                    continue
                session.run(f"DROP INDEX `{record['name'].replace('`', '``')}` IF EXISTS").consume()
                result["indexes_dropped"] += 1
            progress(f"wipe: dropped {result['indexes_dropped']} indexes")
            # Relationships first, then nodes, in fixed-size transactions. DETACH DELETE per node batch is not
            # safe here: one SourceTable/DatasetRelease node can own millions of relationships, and all of them
            # would land in a single transaction (MemoryPoolOutOfMemoryError).
            for what, count_q, delete_q in (
                ("relationships", "MATCH ()-[r]->() RETURN count(r) AS c",
                 "MATCH ()-[r]->() WITH r LIMIT $n DELETE r RETURN count(*) AS c"),
                ("nodes", "MATCH (n) RETURN count(n) AS c",
                 "MATCH (n) WITH n LIMIT $n DELETE n RETURN count(*) AS c"),
            ):
                total = session.run(count_q).single()["c"]
                progress(f"wipe: deleting {total} {what}")
                done = reported = 0
                while True:
                    deleted = session.execute_write(lambda tx: tx.run(delete_q, n=int(batch_size)).single()["c"])
                    if not deleted:
                        break
                    done += deleted
                    if done - reported >= 500_000:
                        reported = done
                        progress(f"wipe: {what} {done}/{total}")
                result[f"{what}_deleted"] = done
                progress(f"wipe: {what} deleted {done}")
    progress("wipe: done")
    result["status"] = "ok"
    return result


class Neo4jImportState:
    """What is already in Neo4j: ImportRun status per dataset and cheap spot checks of emitted batches."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.uri, self.user, self.password, self.database = uri, user, password, database

    def _run(self, query: str, **params) -> list[dict[str, Any]]:
        with _driver(self.uri, self.user, self.password) as driver:
            with driver.session(database=self.database) as session:
                return session.run(query, **params).data()

    def runs(self, dataset_id: str) -> list[dict[str, Any]]:
        return self._run(
            "MATCH (r:ImportRun)-[:IMPORTS]->(rel:DatasetRelease)-[:RELEASE_OF]->(:Dataset {key: $ds}) "
            "RETURN r.key AS run_key, rel.key AS release_key, r.status AS status, r.config_sha256 AS config_sha256, "
            "r.rule_sha256 AS rule_sha256, r.input_fingerprint AS input_fingerprint, r.finished_at AS finished_at",
            ds=dataset_id)

    def row_exists(self, batch: dict[str, Any], row: dict[str, Any]) -> bool:
        """Point lookup through the unique key constraints; never scans a label or relationship type."""
        from .cypher import _safe_name
        if batch["kind"] == "node":
            query = f"MATCH (n:{_safe_name(batch['label'])} {{key: $key}}) RETURN count(n) AS c"
            return self._run(query, key=row["key"])[0]["c"] > 0
        query = (f"MATCH (a:{_safe_name(batch['start_label'])} {{key: $s}})-[r:{_safe_name(batch['type'])} {{key: $k}}]->"
                 f"(b:{_safe_name(batch['end_label'])} {{key: $e}}) RETURN count(r) AS c")
        return self._run(query, s=row["start_key"], e=row["end_key"], k=row["props"]["key"])[0]["c"] > 0

    def mark_completed(self, run_key: str, input_fingerprint: str, finished_at: str) -> None:
        self._run("MATCH (r:ImportRun {key: $k}) SET r.status = 'completed', r.input_fingerprint = $fp, r.finished_at = $at",
                  k=run_key, fp=input_fingerprint, at=finished_at)
