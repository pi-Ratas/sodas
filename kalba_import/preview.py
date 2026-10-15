"""Small-sample preview of what a dataset import would write, using the real mapping code."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .inspect import inspect_dataset
from .model import GraphRow, RelRow
from .planner import context_for, record_key
from .profiles import Profile
from .semantics import AUTHORITY_SCHEMES, Entity, role_name, semantic_for_record, _tv
from .util import canonical_json, dict_rows

TECHNICAL_LABELS = {"SourceRecord", "SourceTable", "DatasetRelease", "Dataset", "ImportRun", "RawReference"}
CONTEXT_ROLES = {"LanguageTable", "ParameterTable", "CodeTable", "CognatesetTable"}
FORM_LINKED_ROLES = {"CognateTable": "formReference", "BorrowingTable": "targetFormReference"}

AUTHORITY_ENRICHES = {
    "glottolog": "oficialus pavadinimas, lygis (šeima / kalba / dialektas), genealogija PARENT_OF, koordinatės, ISO 639-3",
    "concepticon": "oficiali gloss, apibrėžimas, semantinis laukas, ontologinė kategorija, sąvokų ryšiai (narrower, partof …)",
}

_ONLY_DIGITS = re.compile(r"^(?=.*\d)[\d\W_]+$")
# Linguistic strings: digits can be legitimate orthography (ASJP "fo7"), so only the digits-only rule applies.
LEXICAL_LABELS = {"Form", "Lexeme", "ProtoForm"}


def _row_matches(needle: str | None, row: dict[str, str], extra: list[str]) -> bool:
    if not needle:
        return True
    hay = " ".join([*(str(v) for v in row.values() if v), *extra]).casefold()
    return needle in hay


def _referenced_names(ctx, table, row) -> list[str]:
    names = []
    for kind, term in (("languages", "languageReference"), ("parameters", "parameterReference")):
        ent = ctx.lookup(kind, _tv(table, row, term))
        if ent:
            names.append(ent.display)
    return names


def _unescape(part: str) -> str:
    return part.replace("%7C", "|").replace("%2F", "/").replace("%25", "%")


def key_token(key: str) -> str:
    """The source-local ID inside a semantic key, used to pre-filter rows before mapping them."""
    tail = key.rsplit("|", 1)[-1] if "|" in key else key.rsplit(":", 1)[-1]
    return _unescape(tail)


class DatasetPreview:
    """Inspect + reference context for one dataset, reused by sample, missing-endpoint lookup and expand."""

    def __init__(self, dataset_id: str, root: Path, profile: Profile):
        self.dataset_id = dataset_id
        self.profile = profile
        self.ins = inspect_dataset(dataset_id, root, profile, fast=True)
        self.release = f"{dataset_id}@preview"
        self.ctx = context_for(dataset_id, self.release, profile, self.ins.tables)
        self.by_key: dict[str, Entity] = {}
        for kind in ("languages", "parameters", "codes", "cognatesets"):
            for ent in getattr(self.ctx, kind).values():
                self.by_key[ent.key] = ent
        self.has_driver = any(role_name(t.role) in {"FormTable", "ValueTable"} for t in self.ins.tables)

    def row_tables(self):
        """Tables whose rows are mapped one by one (context tables are already held in by_key)."""
        return [t for t in self.ins.tables if not (role_name(t.role) in CONTEXT_ROLES and t.dialect.get("adapter") != "glottolog_ini_tree")]

    def map_row(self, table, rn, row, nodes, rels, records):
        rkey = record_key(self.release, table, rn, row)[0]
        records[rkey] = {"table": table.url, "row_number": rn, "raw": row}
        semantic_for_record(self.ctx, table, rn, row, rkey, nodes, rels)

    def scan(self, tokens: set[str], max_scan: int):
        """Yield (table, rn, row) for rows that contain one of ``tokens`` as a whole cell value."""
        scanned = 0
        for table in self.row_tables():
            try:
                for rn, row in dict_rows(table.path, table.dialect):
                    scanned += 1
                    if scanned > max_scan:
                        return
                    if tokens.intersection(row.values()):
                        yield table, rn, row
            except Exception:
                continue

    def find_nodes(self, keys: set[str], max_scan: int = 300_000) -> dict[str, GraphRow]:
        """Locate the owning rows of nodes that are only referenced (edge endpoints outside the sample)."""
        found: dict[str, GraphRow] = {}
        for key in keys:
            ent = self.by_key.get(key)
            if ent:
                found.update({n.key: n for n in ent.nodes if n.key == key})
        wanted = keys - set(found)
        if not wanted:
            return found
        for table, rn, row in self.scan({key_token(k) for k in wanted}, max_scan):
            nodes: dict[str, list[GraphRow]] = defaultdict(list)
            self.map_row(table, rn, row, nodes, [], {})
            for rows in nodes.values():
                for n in rows:
                    if n.key in wanted and n.key not in found:
                        found[n.key] = n
            if wanted <= set(found):
                break
        return found

    def sample(self, sample: int, needle: str | None, max_scan: int):
        nodes: dict[str, list[GraphRow]] = defaultdict(list)
        rels: list[RelRow] = []
        records: dict[str, dict[str, Any]] = {}
        tables_out = []
        sampled_form_ids: set[str] = set()
        rank = {"FormTable": 0, "ValueTable": 0}
        ordered = sorted(self.ins.tables, key=lambda t: rank.get(role_name(t.role), 2 if role_name(t.role) in FORM_LINKED_ROLES else 1))
        for table in ordered:
            role = role_name(table.role)
            taken = scanned = 0
            info = {"url": table.url, "role": role, "row_count": table.row_count if table.row_count >= 0 else None,
                    "columns": [c.name for c in table.columns], "error": None}
            if self.has_driver and role in CONTEXT_ROLES:
                # Languages, concepts, codes and cognate sets enter the sample through the rows that reference them.
                tables_out.append({**info, "sampled": 0, "scanned": 0, "via_references": True})
                continue
            link_term = FORM_LINKED_ROLES.get(role)
            try:
                for rn, row in dict_rows(table.path, table.dialect):
                    scanned += 1
                    if scanned > max_scan or taken >= sample:
                        break
                    if link_term and sampled_form_ids:
                        if _tv(table, row, link_term) not in sampled_form_ids:
                            continue
                    elif not _row_matches(needle, row, _referenced_names(self.ctx, table, row)):
                        continue
                    self.map_row(table, rn, row, nodes, rels, records)
                    if role == "FormTable":
                        fid = _tv(table, row, "id")
                        if fid:
                            sampled_form_ids.add(str(fid))
                    taken += 1
            except Exception as exc:
                info["error"] = str(exc)
            tables_out.append({**info, "sampled": taken, "scanned": scanned})
        return nodes, rels, records, tables_out

    def expand(self, key: str, limit: int = 150, max_scan: int = 300_000) -> dict[str, Any]:
        """All relationships of one node in this dataset (bounded by ``limit`` and ``max_scan``)."""
        nodes: dict[str, list[GraphRow]] = defaultdict(list)
        rels: list[RelRow] = []
        records: dict[str, dict[str, Any]] = {}
        hits: list[RelRow] = []
        for ent in self.by_key.values():
            for r in ent.rels:
                if key in (r.start_key, r.end_key):
                    hits.append(r)
                    nodes[ent.label].extend(ent.nodes)
        truncated = False
        scanned_rows = 0
        for table, rn, row in self.scan({key_token(key)}, max_scan):
            scanned_rows += 1
            row_nodes: dict[str, list[GraphRow]] = defaultdict(list)
            row_rels: list[RelRow] = []
            row_records: dict[str, dict[str, Any]] = {}
            self.map_row(table, rn, row, row_nodes, row_rels, row_records)
            touching = [r for r in row_rels if key in (r.start_key, r.end_key)]
            if not touching:
                continue
            if len(hits) >= limit:
                truncated = True
                break
            hits.extend(touching)
            ends = {k for r in touching for k in (r.start_key, r.end_key)}
            for label, rows in row_nodes.items():
                nodes[label].extend(n for n in rows if n.key in ends)
            records.update(row_records)
        payload = build_graph(self, nodes, hits, records)
        payload.update({"key": key, "relationships": len(hits), "truncated": truncated, "limit": limit})
        return payload


def build_graph(session: DatasetPreview, nodes: dict[str, list[GraphRow]], rels: list[RelRow],
                records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node_index: dict[str, GraphRow] = {}
    for label_rows in nodes.values():
        for n in label_rows:
            node_index.setdefault(n.key, n)
    # Pull in owners of referenced objects (language, concept, code, cognate set) so no edge dangles.
    pending = [r.end_key for r in rels] + [r.start_key for r in rels]
    seen_pull = set()
    while pending:
        key = pending.pop()
        if key in node_index or key in seen_pull:
            continue
        seen_pull.add(key)
        ent = session.by_key.get(key)
        if ent is None:
            continue
        for n in ent.nodes:
            node_index.setdefault(n.key, n)
        for r in ent.rels:
            rels.append(r)
            pending.extend([r.start_key, r.end_key])
    # Endpoints owned by rows outside the sample (Glottolog parent, Concepticon relation target, ...).
    endpoint_labels = {}
    for r in rels:
        endpoint_labels.setdefault(r.start_key, r.start_label)
        endpoint_labels.setdefault(r.end_key, r.end_label)
    missing = {k for k in endpoint_labels if k not in node_index}
    if missing:
        node_index.update(session.find_nodes(missing))

    out_nodes: dict[str, dict[str, Any]] = {}
    for key, n in node_index.items():
        props = {k: v for k, v in n.props.items() if v is not None}
        out_nodes[key] = {"id": key, "label": n.label, "display_name": props.get("display_name"), "dataset": props.get("dataset"),
                          "props": props}
        if key in missing:
            out_nodes[key]["outside_sample"] = True
    out_edges = []
    seen_edges = set()
    for r in rels:
        ek = (r.start_key, r.rel_type, r.end_key, r.props.get("key"))
        if ek in seen_edges:
            continue
        seen_edges.add(ek)
        for key, label in ((r.start_key, r.start_label), (r.end_key, r.end_label)):
            if key not in out_nodes:
                out_nodes[key] = {"id": key, "label": label, "display_name": None, "dataset": None,
                                  "caption": f"{label} · {key_token(key)} (nerasta)", "props": {"key": key}, "missing": True}
        out_edges.append({"id": "|".join(str(x) for x in ek), "source": r.start_key, "target": r.end_key, "type": r.rel_type,
                          "props": {k: v for k, v in r.props.items() if v is not None}})
    for rkey, rec in records.items():
        out_nodes[rkey] = {"id": rkey, "label": "SourceRecord", "display_name": f"{rec['table']} #{rec['row_number']}",
                           "dataset": session.dataset_id, "technical": True,
                           "props": {"key": rkey, "raw_json": canonical_json(rec["raw"])}}
    for n in list(out_nodes.values()):
        src = n["props"].get("source_record_key")
        if src in records and n["label"] not in TECHNICAL_LABELS:
            out_edges.append({"id": f"{n['id']}|src", "source": n["id"], "target": src, "type": "source_record_key",
                              "technical": True, "props": {}})
    for n in out_nodes.values():
        if n["label"] == "ExternalIdentifier":
            auth = n["props"].get("authority")
            n["needs"] = auth if auth and auth != session.dataset_id else None
    return {"nodes": list(out_nodes.values()), "edges": out_edges}


def preview_dataset(dataset_id: str, root: Path, profile: Profile, sample: int = 25, filter_text: str | None = None,
                    max_scan: int = 300_000, neo4j_datasets: set[str] | None = None,
                    selected: set[str] | None = None, session: DatasetPreview | None = None) -> dict[str, Any]:
    needle = (filter_text or "").strip().casefold() or None
    session = session or DatasetPreview(dataset_id, root, profile)
    ins, ctx, by_key = session.ins, session.ctx, session.by_key
    nodes, rels, records, tables_out = session.sample(sample, needle, max_scan)
    graph = build_graph(session, nodes, rels, records)
    out_nodes = {n["id"]: n for n in graph["nodes"]}
    out_edges = graph["edges"]

    # Schema summary
    label_counts = Counter(n["label"] for n in out_nodes.values() if not n.get("technical"))
    patterns = Counter((out_nodes[e["source"]]["label"], e["type"], out_nodes[e["target"]]["label"])
                       for e in out_edges if not e.get("technical"))
    label_props: dict[str, dict[str, Any]] = defaultdict(dict)
    for n in out_nodes.values():
        if n.get("technical"):
            continue
        for k, v in n["props"].items():
            if k.startswith("search_") or k in {"normalization_rule", "normalization_version", "dataset_release"}:
                continue
            label_props[n["label"]].setdefault(k, v)

    # Dependencies on other datasets: over the whole context, not only the sample.
    neo4j_datasets = neo4j_datasets or set()
    selected = selected or set()
    dep_counts: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    all_ents = list(by_key.values())
    for ent in all_ents:
        for n in ent.nodes:
            if n.label == "ExternalIdentifier":
                dep_counts[n.props["scheme"]][ent.label] += 1
                if len(examples[n.props["scheme"]]) < 5:
                    examples[n.props["scheme"]].append(f"{ent.display} → {n.props['value']}")
    context_eids = {x.key for e in all_ents for x in e.nodes if x.label == "ExternalIdentifier"}
    for e in out_edges:
        target = out_nodes[e["target"]]
        if target["label"] == "ExternalIdentifier" and target["id"] not in context_eids:
            scheme = target["props"].get("scheme", "?")
            dep_counts[scheme][out_nodes[e["source"]]["label"] + " (imtyje)"] += 1
            if len(examples[scheme]) < 5:
                examples[scheme].append(f"{out_nodes[e['source']]['display_name']} → {target['props'].get('value')}")
    dependencies = []
    for scheme, counts in sorted(dep_counts.items()):
        authority = AUTHORITY_SCHEMES.get(scheme, (None,))[0]
        if authority == dataset_id:
            continue
        dependencies.append({
            "scheme": scheme, "authority": authority, "objects": dict(counts), "examples": examples[scheme],
            "enriches": AUTHORITY_ENRICHES.get(authority or "", ""),
            "in_neo4j": authority in neo4j_datasets, "selected": authority in selected,
        })
    for authority in profile.authorities:
        if authority != dataset_id and not any(d["authority"] == authority for d in dependencies):
            dependencies.append({"scheme": None, "authority": authority, "objects": {}, "examples": [],
                                 "enriches": AUTHORITY_ENRICHES.get(authority, ""), "declared_only": True,
                                 "in_neo4j": authority in neo4j_datasets, "selected": authority in selected})
    # Quality warnings on human-readable captions (contract §8 "Žmogui skaitomas grafas").
    issues: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for n in out_nodes.values():
        if n.get("technical") or n["label"] == "ExternalIdentifier":
            continue
        disp = n["display_name"]
        src = n["props"].get("source_id")
        if n.get("missing"):
            issues[("error", n["label"], "ryšio galo mazgo šis duomenynas nesukuria – tikrame importe šis ryšys nebus įrašytas")].append(n["id"])
        elif not disp:
            issues[("error", n["label"], "nėra display_name")].append(n["id"])
        elif n["props"].get("unresolved_reference"):
            issues[("warning", n["label"], "nuoroda į objektą, kurio savininko eilutės nėra (rodomas tipas + ID)")].append(disp)
        elif _ONLY_DIGITS.match(str(disp)):
            issues[("error", n["label"], "display_name sudarytas tik iš skaičių / ženklų – tikriausiai techninis ID")].append(str(disp))
        elif (n["label"] not in LEXICAL_LABELS and src and str(disp) == str(src) and re.search(r"[\d_]", str(disp))):
            issues[("warning", n["label"], "display_name sutampa su šaltinio ID – patikrinkite, ar tai žmogui suprantamas pavadinimas")].append(str(disp))
    quality = [{"severity": sev, "label": label, "message": msg, "count": len(ex), "examples": ex[:6]}
               for (sev, label, msg), ex in sorted(issues.items())]

    return {
        "dataset_id": dataset_id,
        "title": profile.raw.get("title") or dataset_id,
        "filter": filter_text or "",
        "sample": sample,
        "tables": tables_out,
        "nodes": list(out_nodes.values()),
        "edges": out_edges,
        "schema": {
            "labels": dict(sorted(label_counts.items())),
            "patterns": [{"start": s, "type": t, "end": e, "count": c} for (s, t, e), c in sorted(patterns.items())],
            "properties": {k: v for k, v in sorted(label_props.items())},
        },
        "context_sizes": {k: len(getattr(ctx, k)) for k in ("languages", "parameters", "codes", "cognatesets")},
        "dependencies": dependencies,
        "quality": quality,
        "diagnostics": [d.__dict__ for d in [*ins.diagnostics, *ctx.diagnostics] if d.code != "PROFILE_UNVERIFIED"],
    }
