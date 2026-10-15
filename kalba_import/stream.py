"""Bounded-memory emitter for large CLDF datasets."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

from .cypher import _dedupe_nodes, _dedupe_rels, _rel_key, constraint_cypher, node_cypher, rel_cypher
from .inspect import inspect_dataset
from .model import Diagnostic, GraphRow, RelRow
from .planner import (_fk_value_tuples, _is_external_fk_resource, _target_table, context_for, run_key_for,
                      record_key, release_key, table_identity, table_key)
from .semantics import rule_sha_for, semantic_for_record
from .util import canonical_json, dict_rows, sha256_text


def emit_large(dataset_id, root, profile, out_dir, batch_size=1000, known_row_counts=None, known_manifest=None):
    """Write graph rows through a disk spool, keeping only one source row in memory."""
    ins = inspect_dataset(dataset_id, root, profile, known_row_counts=known_row_counts, known_manifest=known_manifest)
    release, msha = release_key(dataset_id, ins.manifest)
    rule_sha = rule_sha_for(dataset_id, profile)
    ctx = context_for(dataset_id, release, profile, ins.tables)
    diagnostics = list(ins.diagnostics) + ctx.diagnostics
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kalba-spool-", dir=out_dir) as tmp:
        db = sqlite3.connect(Path(tmp) / "rows.sqlite")
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA temp_store=FILE")
        db.execute("PRAGMA cache_size=-8192")
        db.execute("CREATE TABLE nodes(label TEXT, key TEXT, data TEXT)")
        db.execute("CREATE TABLE rels(kind TEXT, key TEXT, data TEXT)")
        db.execute("CREATE TABLE refs(scope TEXT, resource TEXT, columns TEXT, vals TEXT, key TEXT)")
        db.execute("CREATE INDEX refs_lookup ON refs(scope, resource, columns, vals)")
        def add_rows(nodes, rels):
            for label, rows in nodes.items():
                db.executemany("INSERT INTO nodes VALUES (?,?,?)", ((label, r.key, canonical_json(r.props)) for r in rows))
            db.executemany("INSERT INTO rels VALUES (?,?,?)", (
                (canonical_json([r.rel_type, r.start_label, r.end_label]), r.props.get("key") or _rel_key(r),
                 canonical_json([r.start_key, r.end_key, r.props])) for r in rels))
        from .model import CONTRACT_VERSION
        import uuid
        run_key = run_key_for(release, profile.config_sha256)
        seed = defaultdict(list)
        seed_rels = []
        for label, key, props in (("Dataset", dataset_id, {"title": profile.raw.get("title") or dataset_id}),
                                  ("DatasetRelease", release, {"manifest_sha256": msha}),
                                  ("ImportRun", run_key, {"status": "planned", "profile_version": profile.profile_version,
                                                           "config_sha256": profile.config_sha256, "rule_sha256": rule_sha,
                                                           "contract_version": CONTRACT_VERSION})):
            seed[label].append(GraphRow(label, key, {"key": key, **props}))
        seed_rels.extend([RelRow("DatasetRelease", release, "RELEASE_OF", "Dataset", dataset_id, {}),
                          RelRow("ImportRun", run_key, "IMPORTS", "DatasetRelease", release, {})])
        add_rows(seed, seed_rels)
        source_records = assertions = pending = 0
        # Index referenced target columns only. Large form/value tables are never held in memory.
        targets = defaultdict(set)
        for table in ins.tables:
            for fk in table.foreign_keys:
                target = _target_table(table, ins.tables, fk.reference_resource)
                if target is not None:
                    targets[table_identity(target)].add(fk.reference_columns)
        ordered = []
        visited = set()
        visiting = set()
        def visit(table):
            tid = table_identity(table)
            if tid in visited:
                return
            if tid in visiting:
                raise ValueError(f"cyclic foreign keys in {table.url}")
            visiting.add(tid)
            for fk in table.foreign_keys:
                target = _target_table(table, ins.tables, fk.reference_resource)
                if target is not None:
                    visit(target)
            visiting.remove(tid)
            visited.add(tid)
            ordered.append(table)
        for table in ins.tables:
            visit(table)
        warned = set()
        def emit_references(table, rn, row, rkey):
            nonlocal pending
            for fk in table.foreign_keys:
                vals_list = _fk_value_tuples(table, row, fk.columns)
                if not vals_list:
                    continue
                target = _target_table(table, ins.tables, fk.reference_resource)
                if target is None:
                    if _is_external_fk_resource(fk.reference_resource):
                        if fk.reference_resource not in warned:
                            diagnostics.append(Diagnostic("warning", "FK_EXTERNAL_RESOURCE", f"{table.url} references external resource {fk.reference_resource}", table=table.url))
                            warned.add(fk.reference_resource)
                        continue
                    if len(diagnostics) < 100:
                        diagnostics.append(Diagnostic("error", "FK_TARGET_TABLE_MISSING", f"{table.url}:{rn} references missing table {fk.reference_resource}", rkey, table.url))
                    continue
                for vals in vals_list:
                    hits = db.execute("SELECT key FROM refs WHERE scope=? AND resource=? AND columns=? AND vals=? LIMIT 2",
                        (target.source_metadata or "", target.url, canonical_json(fk.reference_columns), canonical_json(vals))).fetchall()
                    if len(hits) == 1:
                        add_rows({}, [RelRow("SourceRecord", rkey, "REFERS_TO_RECORD", "SourceRecord", hits[0][0], {"columns": ",".join(fk.columns)})])
                    else:
                        status = "missing" if not hits else "ambiguous"
                        if len(diagnostics) < 100:
                            diagnostics.append(Diagnostic("error", "FK_NOT_FOUND" if not hits else "FK_AMBIGUOUS",
                                f"{table.url}:{rn} unresolved FK {fk.columns}={vals} -> {fk.reference_resource}.{fk.reference_columns}", rkey, table.url))
                        rrkey = "rawref:" + sha256_text(f"{rkey}|{','.join(fk.columns)}|{vals}|{fk.reference_resource}|{status}")
                        add_rows({"RawReference": [GraphRow("RawReference", rrkey, {"key": rrkey, "column": ",".join(fk.columns),
                            "target_raw": "|".join(vals), "resolution_status": status})]},
                            [RelRow("RawReference", rrkey, "FROM_RECORD", "SourceRecord", rkey, {})])
                        pending += 1
        for table in ordered:
            tkey = table_key(release, table)
            schema = {"columns": [c.__dict__ for c in table.columns], "primary_key": list(table.primary_key),
                      "foreign_keys": [f.__dict__ for f in table.foreign_keys], "dialect": table.dialect}
            add_rows({"SourceTable": [GraphRow("SourceTable", tkey, {"key": tkey, "url": table.url, "role": table.role,
                      "schema_json": canonical_json(schema), "row_count": table.row_count})]},
                     [RelRow("SourceTable", tkey, "IN_RELEASE", "DatasetRelease", release, {})])
            scope = table.source_metadata or ""
            for rn, row in dict_rows(table.path, table.dialect):
                rkey, local_id, unstable = record_key(release, table, rn, row)
                raw = canonical_json(row)
                nodes = defaultdict(list)
                rels = [RelRow("SourceRecord", rkey, "IN_TABLE", "SourceTable", tkey, {})]
                nodes["SourceRecord"].append(GraphRow("SourceRecord", rkey, {"key": rkey, "local_id": local_id,
                    "row_sha256": sha256_text(raw), "raw_json": raw, "row_number": rn, "unstable_key": unstable}))
                semantic_for_record(ctx, table, rn, row, rkey, nodes, rels)
                assertions += len(nodes.get("Assertion", []))
                source_records += 1
                add_rows(nodes, rels)
                emit_references(table, rn, row, rkey)
                for cols in targets.get(table_identity(table), ()):
                    for vals in _fk_value_tuples(table, row, cols):
                        db.execute("INSERT INTO refs VALUES (?,?,?,?,?)", (scope, table.url, canonical_json(cols), canonical_json(vals), rkey))
            db.commit()
        (out_dir / "constraints.cypher").write_text(constraint_cypher(), encoding="utf-8")
        manifest = {"dataset_id": dataset_id, "release_key": release, "manifest_sha256": msha, "batches": [],
                    "diagnostics": [d.__dict__ for d in diagnostics]}
        def write_batch(kind, ident, rows, number):
            if not rows:
                return
            if kind == "node":
                label = ident
                cyp = f"node_{label}.cypher"
                (out_dir / cyp).write_text(node_cypher(label), encoding="utf-8")
                name = f"node_{label}_{number:04d}.ndjson"
                entry = {"kind": kind, "label": label, "cypher": cyp, "params": name, "rows": len(rows)}
            else:
                rel_type, start, end = json.loads(ident)
                cyp = f"rel_{start}_{rel_type}_{end}.cypher"
                (out_dir / cyp).write_text(rel_cypher(rel_type, start, end), encoding="utf-8")
                name = f"rel_{start}_{rel_type}_{end}_{number:04d}.ndjson"
                entry = {"kind": "relationship", "type": rel_type, "start_label": start, "end_label": end,
                         "cypher": cyp, "params": name, "rows": len(rows)}
            (out_dir / name).write_text("\n".join(canonical_json(r) for r in rows) + "\n", encoding="utf-8")
            manifest["batches"].append(entry)
        # Sorted spool enables one-key-at-a-time deduplication without a large dictionary.
        for kind, query in (("node", "SELECT label,key,data FROM nodes ORDER BY label,key,rowid"),
                            ("relationship", "SELECT kind,key,data FROM rels ORDER BY kind,key,rowid")):
            current_ident = current_key = None
            same = []
            batch = []
            number = 0
            def flush_key():
                nonlocal same, batch, number
                if not same:
                    return
                if kind == "node":
                    batch.extend(_dedupe_nodes([GraphRow(current_ident, current_key, json.loads(x)) for x in same]))
                else:
                    rel_type, start, end = json.loads(current_ident)
                    batch.extend(_dedupe_rels([RelRow(start, json.loads(x)[0], rel_type, end, json.loads(x)[1], json.loads(x)[2]) for x in same]))
                same = []
                if len(batch) >= batch_size:
                    write_batch(kind, current_ident, batch, number)
                    batch = []
                    number += 1
            for ident, key, data in db.execute(query):
                if current_ident is not None and (ident != current_ident or key != current_key):
                    flush_key()
                    if ident != current_ident:
                        write_batch(kind, current_ident, batch, number)
                        batch = []
                        number = 0
                current_ident, current_key = ident, key
                same.append(data)
            flush_key()
            if batch:
                write_batch(kind, current_ident, batch, number)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        db.close()
    return manifest, {"source_records": source_records, "assertions": assertions, "pending_references": pending,
                      "diagnostics": diagnostics, "release_key": release, "config_sha256": profile.config_sha256, "rule_sha256": rule_sha}
