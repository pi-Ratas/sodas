"""Writing LKEŽDB plans to Neo4j and taking them away again – only ever nodes and relationships with
``dataset = "lkezdb"``; other datasets, constraints and indexes are never touched.

A node or relationship lists the LKEŽDB articles it came from (``source_record_keys``). Including a word first takes
away what its articles contributed earlier, then merges the new plan; removing a word takes its articles' keys
away and deletes whatever is left with none."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .plan import DATASET, NEW_CONSTRAINT_LABELS, OWN_LABELS

LABELS = "|".join(OWN_LABELS)
# Every LKEŽDB node's key starts with "lkezdb" (plan.py): with this condition Neo4j looks them up in the key indexes of
# their labels instead of reading all nodes of those labels (millions of source records and forms: 20 s → 0.1 s)
OWN = f"n.key STARTS WITH '{DATASET}' AND n.dataset = $ds"
_SAFE = set(OWN_LABELS) | {"Concept"}


def _name(x: str) -> str:
    if not x.replace("_", "").isalnum():
        raise ValueError(f"netinkamas vardas: {x!r}")
    return x


class Graph:
    """Thin layer over the official driver (settings as everywhere else: neo4j.yaml / environment)."""

    def __init__(self, settings_func):
        self.settings_func = settings_func
        self._driver = None
        self._ident = None

    def driver(self):
        s = self.settings_func()
        ident = (s["uri"], s["user"], s["password"])
        if self._driver is None or self._ident != ident:
            from neo4j import GraphDatabase
            if self._driver is not None:
                self._driver.close()
            self._driver = GraphDatabase.driver(s["uri"], auth=(s["user"], s["password"]), notifications_min_severity="OFF")
            self._ident = ident
        return self._driver, s["database"]

    def run(self, query: str, **params) -> list[dict[str, Any]]:
        driver, db = self.driver()
        with driver.session(database=db) as session:
            return [r.data() for r in session.run(query, **params)]

    def write(self, query: str, **params) -> list[dict[str, Any]]:
        driver, db = self.driver()
        with driver.session(database=db) as session:
            return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def ensure_constraints(g: Graph) -> None:
    for label in NEW_CONSTRAINT_LABELS:
        g.run(f"CREATE CONSTRAINT kalba_{label.lower()}_key IF NOT EXISTS FOR (n:{_name(label)}) REQUIRE n.key IS UNIQUE")


def remove_records(g: Graph, records: list[str]) -> dict[str, int]:
    """Take these articles' contributions away; delete relationships and nodes nothing else keeps."""
    if not records:
        return {"relationships": 0, "nodes": 0}
    rels = g.write(
        f"MATCH (n:{LABELS}) WHERE {OWN} AND any(k IN n.source_record_keys WHERE k IN $recs) "
        "MATCH (n)-[r]-() WHERE r.dataset = $ds AND any(k IN r.source_record_keys WHERE k IN $recs) "
        "WITH DISTINCT r SET r.source_record_keys = [k IN r.source_record_keys WHERE NOT k IN $recs] "
        "WITH r WHERE size(r.source_record_keys) = 0 DELETE r RETURN count(*) AS n", ds=DATASET, recs=records)
    nodes = g.write(
        f"MATCH (n:{LABELS}) WHERE {OWN} AND any(k IN n.source_record_keys WHERE k IN $recs) "
        "SET n.source_record_keys = [k IN n.source_record_keys WHERE NOT k IN $recs] "
        "WITH n WHERE size(n.source_record_keys) = 0 DETACH DELETE n RETURN count(*) AS n", ds=DATASET, recs=records)
    # a node that stays (it is kept by another word) must not point at a removed article as its first source
    g.write(f"MATCH (n:{LABELS}) WHERE {OWN} AND n.source_record_key IN $recs AND size(n.source_record_keys) > 0 "
            "SET n.source_record_key = n.source_record_keys[0]", ds=DATASET, recs=records)
    return {"relationships": rels[0]["n"] if rels else 0, "nodes": nodes[0]["n"] if nodes else 0}


def write_plan(g: Graph, plan: dict[str, Any], batch: int = 500) -> dict[str, int]:
    """Merge the plan's nodes and relationships (after taking the word's earlier contribution away)."""
    ensure_constraints(g)
    removed = remove_records(g, plan["records"])
    by_label: dict[str, list] = defaultdict(list)
    for n in plan["nodes"]:
        by_label[_name(n["label"])].append({"key": n["key"], "props": {k: v for k, v in n["props"].items() if k != "source_record_keys"},
                                             "recs": n["props"]["source_record_keys"]})
    for label, rows in by_label.items():
        for i in range(0, len(rows), batch):
            g.write(f"UNWIND $rows AS row MERGE (n:{label} {{key: row.key}}) "
                    "ON CREATE SET n.source_record_keys = [] "
                    "SET n += row.props, n.source_record_keys = [k IN n.source_record_keys WHERE NOT k IN row.recs] + row.recs",
                    rows=rows[i:i + batch])
    by_type: dict[tuple, list] = defaultdict(list)
    for r in plan["relationships"]:
        if r["end_label"] not in _SAFE:
            raise ValueError(f"netinkama ryšio pabaiga: {r['end_label']}")
        by_type[(_name(r["type"]), _name(r["start_label"]), _name(r["end_label"]))].append(
            {"s": r["start"], "e": r["end"], "key": r["props"]["key"],
             "props": {k: v for k, v in r["props"].items() if k != "source_record_keys"}, "recs": r["props"]["source_record_keys"]})
    for (rtype, sl, el), rows in by_type.items():
        for i in range(0, len(rows), batch):
            g.write(f"UNWIND $rows AS row MATCH (a:{sl} {{key: row.s}}) MATCH (b:{el} {{key: row.e}}) "
                    f"MERGE (a)-[r:{rtype} {{key: row.key}}]->(b) ON CREATE SET r.source_record_keys = [] "
                    "SET r += row.props, r.source_record_keys = [k IN r.source_record_keys WHERE NOT k IN row.recs] + row.recs",
                    rows=rows[i:i + batch])
    return {"nodes": len(plan["nodes"]), "relationships": len(plan["relationships"]),
            "removed_nodes": removed["nodes"], "removed_relationships": removed["relationships"], **verify(g, plan)}


def verify(g: Graph, plan: dict[str, Any]) -> dict[str, int]:
    keys = [n["key"] for n in plan["nodes"]]
    rkeys = [r["props"]["key"] for r in plan["relationships"]]
    n = g.run(f"UNWIND $keys AS k MATCH (n:{LABELS} {{key: k}}) WHERE n.dataset = $ds RETURN count(n) AS c", keys=keys, ds=DATASET)[0]["c"]
    r = g.run(f"MATCH (n:{LABELS})-[r]->() WHERE {OWN} AND r.key IN $keys RETURN count(r) AS c", keys=rkeys, ds=DATASET)[0]["c"]
    if n < len(keys) or r < len(rkeys):
        raise RuntimeError(f"Neo4j importas nepilnas: tikėtasi {len(keys)} mazgų ir {len(rkeys)} ryšių, rasta {n} ir {r}.")
    return {"found_nodes": n, "found_relationships": r}


def counts(g: Graph) -> dict[str, Any]:
    rows = g.run(f"MATCH (n:{LABELS}) WHERE {OWN} RETURN head(labels(n)) AS label, count(*) AS c ORDER BY c DESC", ds=DATASET)
    rels = g.run(f"MATCH (n:{LABELS})-[r]->() WHERE {OWN} AND r.dataset = $ds RETURN count(r) AS c", ds=DATASET)[0]["c"]
    return {"nodes": sum(r["c"] for r in rows), "relationships": rels, "labels": rows}


def delete_all(g: Graph) -> dict[str, int]:
    """Every LKEŽDB node (with its relationships, including those to Glottolog / Concepticon); nothing else."""
    before = counts(g)
    driver, db = g.driver()
    with driver.session(database=db) as session:   # CALL … IN TRANSACTIONS needs an implicit transaction
        session.run(f"MATCH (n:{LABELS}) WHERE {OWN} CALL (n) {{ DETACH DELETE n }} IN TRANSACTIONS OF 2000 ROWS",
                    ds=DATASET).consume()
    after = counts(g)
    return {"deleted_nodes": before["nodes"] - after["nodes"], "deleted_relationships": before["relationships"], "left": after["nodes"]}
