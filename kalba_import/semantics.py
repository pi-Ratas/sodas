"""Row -> human readable research graph mapping (contract v1.1, §3-§4).

Every semantic node is owned by exactly one source table row inside its own
dataset namespace.  References between tables of the same release (a form's
``Language_ID``, ``Parameter_ID``, a value's ``Code_ID`` ...) are resolved
through a :class:`DatasetContext` built before the rows are mapped, so that a
form points to the *same* ``Languoid`` node that ``LanguageTable`` created,
with its real name, instead of a new node whose name is the numeric ID.

Authority objects (``languoid:<glottocode>``, ``concepticon:<id>``) are
created only by their authority dataset.  Other datasets attach
``IDENTIFIED_BY`` edges to shared ``ExternalIdentifier`` nodes; ``resolve``
later links the local node to the authority node.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import CLDF, Diagnostic, GraphRow, RelRow, TableInfo
from .util import canonical_json, column_map, dict_rows, escape_key_part, search_props, sha256_text, value_for_column


RULES_VERSION = "0.2.0"

# scheme -> (authority dataset, authority node label, authority key prefix)
AUTHORITY_SCHEMES = {
    "glottolog:glottocode": ("glottolog", "Languoid", "languoid:"),
    "concepticon:conceptset": ("concepticon", "Concept", "concepticon:"),
}

DEFAULT_GLOSS_COLUMNS = ["Gloss", "gloss_in_source", "ConceptInSource"]
DEFAULT_COGNATESET_COLUMNS = {
    "reconstruction": ["Root_Form", "Root_Form_calc"],
    "meaning": ["Root_Gloss"],
    "language": ["Root_Language", "Root_Language_calc"],
}
MAX_DISPLAY = 120


def role_name(role: str) -> str:
    if role.startswith(CLDF):
        return role.removeprefix(CLDF)
    return role.rsplit("#", 1)[-1] if "#" in role else role


def rule_sha_for(dataset_id: str, profile: Any) -> str:
    return sha256_text(canonical_json({
        "generic_rules": RULES_VERSION,
        "dataset": dataset_id,
        "profile": profile.raw.get("semantics", {}),
        "table_roles": profile.input.get("table_roles", {}),
    }))


def _term(table: TableInfo, suffix: str):
    wanted = CLDF + suffix
    for col in table.columns:
        if col.property_url == wanted:
            return col
    return None


def _tv(table: TableInfo, row: dict[str, str], suffix: str, split: bool = False) -> Any:
    col = _term(table, suffix)
    if col is None:
        return None
    return value_for_column(row, col, split=split)


def _col(table: TableInfo, row: dict[str, str], names: list[str]) -> str | None:
    """First non-empty value among plain (non-CLDF-term) column names."""
    cmap = column_map(table.columns)
    for name in names:
        if name in cmap:
            value = value_for_column(row, cmap[name])
        else:
            value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _short(text: Any) -> str | None:
    if text in (None, ""):
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_DISPLAY else text[: MAX_DISPLAY - 1] + "…"


def relationship_key(release: str, rkey: str, rule_sha: str, rel_type: str, start_key: str, end_key: str,
                     qualifiers: dict[str, Any] | None = None, idx: int = 0) -> str:
    payload = "|".join([release, rkey, rule_sha, rel_type, start_key, end_key, canonical_json(qualifiers or {}), str(idx)])
    return "rel:" + sha256_text(payload)


@dataclass
class Entity:
    """A semantic object owned by one source row, plus what that row creates with it."""
    label: str
    key: str
    display: str
    nodes: list[GraphRow] = field(default_factory=list)
    rels: list[RelRow] = field(default_factory=list)


@dataclass
class DatasetContext:
    dataset_id: str
    release: str
    rule_sha: str
    semantics: dict[str, Any]
    languages: dict[str, Entity] = field(default_factory=dict)
    parameters: dict[str, Entity] = field(default_factory=dict)
    codes: dict[str, Entity] = field(default_factory=dict)
    cognatesets: dict[str, Entity] = field(default_factory=dict)
    wordlist_metadata: set[str | None] = field(default_factory=set)
    owned: set[str] = field(default_factory=set)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    # -- helpers -----------------------------------------------------------
    def props(self, rkey: str, display: Any, source_id: Any = None, *alternates: Any) -> dict[str, Any]:
        flat: list[Any] = []
        for alt in alternates:
            flat.extend(alt if isinstance(alt, list) else [alt])
        props = {"dataset": self.dataset_id, "dataset_release": self.release, "source_record_key": rkey, "source_id": source_id}
        props.update(search_props(display, source_id, *flat))
        return {k: v for k, v in props.items() if v is not None}

    def rel(self, rkey: str, start_label: str, start_key: str, rel_type: str, end_label: str, end_key: str,
            rule_id: str, idx: int = 0, **qualifiers: Any) -> RelRow:
        clean = {k: v for k, v in qualifiers.items() if v not in (None, "")}
        props = {
            "key": relationship_key(self.release, rkey, self.rule_sha, rel_type, start_key, end_key, clean, idx),
            "dataset": self.dataset_id,
            "dataset_release": self.release,
            "source_record_key": rkey,
            "rule_id": rule_id,
            "status": clean.pop("status", "asserted"),
            **clean,
        }
        return RelRow(start_label, start_key, rel_type, end_label, end_key, props)

    def external_id(self, ent: Entity, rkey: str, scheme: str, value: str, rule_id: str) -> None:
        authority = AUTHORITY_SCHEMES.get(scheme, (None,))[0]
        eid = f"{scheme}|{value}"
        ent.nodes.append(GraphRow("ExternalIdentifier", eid, {
            "key": eid, "scheme": scheme, "value": value, "display_name": value, "authority": authority,
        }))
        ent.rels.append(self.rel(rkey, ent.label, ent.key, "IDENTIFIED_BY", "ExternalIdentifier", eid, rule_id,
                                 validity="asserted_by_source"))

    def lookup(self, kind: str, local_id: Any) -> Entity | None:
        if local_id in (None, ""):
            return None
        return getattr(self, kind).get(str(local_id))

    def fallback(self, kind: str, label: str, local_id: str, rkey: str, caption: str) -> Entity:
        """Referenced object with no owning row in this release: explicit, typed caption, never a bare ID."""
        key = f"{self.dataset_id}:{label.lower()}:{escape_key_part(local_id)}"
        display = f"{caption} · {local_id}"
        ent = Entity(label, key, display)
        ent.nodes.append(GraphRow(label, key, {"key": key, "unresolved_reference": True,
                                               **self.props(rkey, display, local_id)}))
        return ent


def _emit(ent: Entity, nodes: dict[str, list[GraphRow]], rels: list[RelRow]) -> None:
    for node in ent.nodes:
        nodes[node.label].append(GraphRow(node.label, node.key, dict(node.props)))
    rels.extend(ent.rels)


# -- owners of referenced objects ----------------------------------------------

def language_entity(ctx: DatasetContext, table: TableInfo, row: dict[str, str], rkey: str) -> Entity:
    local_id = _tv(table, row, "id")
    name = _tv(table, row, "name")
    code = _tv(table, row, "glottocode")
    extra = {
        "glottocode": code,
        "level": _tv(table, row, "level"),
        "iso639p3": _tv(table, row, "iso639P3code"),
        "macroarea": _tv(table, row, "macroarea"),
        "latitude": _tv(table, row, "latitude"),
        "longitude": _tv(table, row, "longitude"),
    }
    if ctx.dataset_id == "glottolog":
        code = code or local_id
        extra["glottocode"] = code
        label, key = "Languoid", f"languoid:{code}"
    else:
        label = ctx.semantics.get("language_table_label", "Languoid")
        key = f"{ctx.dataset_id}:{label.lower()}:{escape_key_part(local_id or rkey)}"
    display = _short(name) or f"{'Society' if label == 'Society' else 'Language'} · {local_id}"
    ent = Entity(label, key, display)
    ent.nodes.append(GraphRow(label, key, {"key": key, "name": name, **{k: v for k, v in extra.items() if v not in (None, "")},
                                           **ctx.props(rkey, display, local_id, code)}))
    if code:
        ctx.external_id(ent, rkey, "glottolog:glottocode", code, "language-glottocode-v1")
    return ent


def parameter_entity(ctx: DatasetContext, table: TableInfo, row: dict[str, str], rkey: str) -> Entity:
    local_id = _tv(table, row, "id")
    name = _tv(table, row, "name")
    cid = _tv(table, row, "concepticonReference")
    is_concept = bool(cid) or table.source_metadata in ctx.wordlist_metadata
    label = "Concept" if is_concept else "Feature"
    key = f"{ctx.dataset_id}:{label.lower()}:{escape_key_part(local_id or rkey)}"
    c_gloss = _col(table, row, ["Concepticon_Gloss"])
    display = _short(name) or _short(c_gloss) or f"{label} · {local_id}"
    props: dict[str, Any] = {"key": key, "label": name or display, "description": _short(_tv(table, row, "description"))}
    if is_concept:
        props.update({"concepticon_id": cid, "concepticon_gloss": c_gloss})
    else:
        props["domain"] = ctx.dataset_id
    ent = Entity(label, key, display)
    ent.nodes.append(GraphRow(label, key, {**{k: v for k, v in props.items() if v not in (None, "")},
                                           **ctx.props(rkey, display, local_id, c_gloss)}))
    if cid:
        ctx.external_id(ent, rkey, "concepticon:conceptset", cid, "parameter-concepticon-v1")
    return ent


def code_entity(ctx: DatasetContext, table: TableInfo, row: dict[str, str], rkey: str) -> Entity:
    local_id = _tv(table, row, "id")
    name = _tv(table, row, "name") or _tv(table, row, "value") or local_id
    param = ctx.lookup("parameters", _tv(table, row, "parameterReference"))
    display = _short(f"{name} — {param.display}" if param else name) or f"Value · {local_id}"
    key = f"{ctx.dataset_id}:feature-value:{escape_key_part(local_id or rkey)}"
    ent = Entity("FeatureValue", key, display)
    ent.nodes.append(GraphRow("FeatureValue", key, {"key": key, "raw_value": name, "domain": ctx.dataset_id,
                                                     **({"description": _short(_tv(table, row, "description"))} if _tv(table, row, "description") else {}),
                                                     **ctx.props(rkey, display, local_id, name)}))
    if param:
        ent.rels.append(ctx.rel(rkey, "FeatureValue", key, "VALUE_OF", param.label, param.key, "code-value-of-v1"))
    return ent


def cognateset_entity(ctx: DatasetContext, table: TableInfo, row: dict[str, str], rkey: str) -> Entity:
    cols = {**DEFAULT_COGNATESET_COLUMNS, **ctx.semantics.get("cognateset_columns", {})}
    local_id = _tv(table, row, "id")
    recon = _col(table, row, cols["reconstruction"])
    meaning = _col(table, row, cols["meaning"])
    root_language = _col(table, row, cols["language"])
    description = _tv(table, row, "description")
    if recon and meaning:
        display = f"{recon} — {meaning}"
    else:
        display = recon or description or f"Cognate set · {local_id}"
    display = _short(display)
    key = f"{ctx.dataset_id}:cognateset:{escape_key_part(local_id or rkey)}"
    ent = Entity("CognateSet", key, display)
    ent.nodes.append(GraphRow("CognateSet", key, {"key": key, "label": display, "reconstruction": recon, "meaning": meaning,
                                                   "root_language": root_language,
                                                   **ctx.props(rkey, display, local_id, recon, meaning)}))
    if recon:
        pkey = f"{ctx.dataset_id}:protoform:{escape_key_part(local_id or rkey)}"
        ent.nodes.append(GraphRow("ProtoForm", pkey, {"key": pkey, "reconstruction": recon, "notation": "source",
                                                      "language": root_language,
                                                      **ctx.props(rkey, _short(recon), local_id, meaning)}))
        ent.rels.append(ctx.rel(rkey, "ProtoForm", pkey, "RECONSTRUCTED_FOR", "CognateSet", key, "cognateset-protoform-v1"))
    return ent


CONTEXT_BUILDERS = {
    "LanguageTable": ("languages", language_entity),
    "ParameterTable": ("parameters", parameter_entity),
    "CodeTable": ("codes", code_entity),
    "CognatesetTable": ("cognatesets", cognateset_entity),
}
CONTEXT_ORDER = ["LanguageTable", "ParameterTable", "CodeTable", "CognatesetTable"]


def build_context(dataset_id: str, release: str, rule_sha: str, semantics: dict[str, Any], tables: list[TableInfo],
                  record_key_func) -> DatasetContext:
    ctx = DatasetContext(dataset_id, release, rule_sha, semantics)
    ctx.wordlist_metadata = {t.source_metadata for t in tables if role_name(t.role) == "FormTable"}
    for role in CONTEXT_ORDER:
        kind, builder = CONTEXT_BUILDERS[role]
        target = getattr(ctx, kind)
        for table in tables:
            if role_name(table.role) != role or table.dialect.get("adapter") == "glottolog_ini_tree":
                continue
            try:
                for rn, row in dict_rows(table.path, table.dialect):
                    local_id = _tv(table, row, "id")
                    if local_id in (None, ""):
                        continue
                    rkey = record_key_func(release, table, rn, row)[0]
                    target.setdefault(str(local_id), builder(ctx, table, row, rkey))
            except Exception as exc:  # reported again by the row pass
                ctx.diagnostics.append(Diagnostic("warning", "CONTEXT_READ_FAILED", f"{table.url}: {exc}", table=table.url))
    return ctx


# -- row mapping ---------------------------------------------------------------------

def semantic_for_record(ctx: DatasetContext, table: TableInfo, row_number: int, row: dict[str, str], rkey: str,
                        nodes: dict[str, list[GraphRow]], rels: list[RelRow]) -> int:
    role = role_name(table.role)
    ds = ctx.dataset_id
    idx = 0
    if role in CONTEXT_BUILDERS:
        _emit(CONTEXT_BUILDERS[role][1](ctx, table, row, rkey), nodes, rels)
        if role == "LanguageTable" and ds == "glottolog" and row.get("Parent"):
            code = _tv(table, row, "glottocode") or _tv(table, row, "id")
            rels.append(ctx.rel(rkey, "Languoid", f"languoid:{row['Parent']}", "PARENT_OF", "Languoid", f"languoid:{code}",
                                "glottolog-tree-parent-v1"))
        return 1
    if role == "FormTable":
        local_id = _tv(table, row, "id")
        form_value = _tv(table, row, "form") or _tv(table, row, "value")
        segments = _tv(table, row, "segments", split=True)
        key = f"{ds}:form:{escape_key_part(local_id or rkey)}"
        display = _short(form_value) or f"Form · {local_id}"
        nodes["Form"].append(GraphRow("Form", key, {"key": key, "written": form_value, "value": _tv(table, row, "value"),
                                                    "segments": segments if isinstance(segments, list) and segments else None,
                                                    **ctx.props(rkey, display, local_id, segments or [])}))
        lex_col = next((c for c in table.columns if c.name == "Local_ID"), None)
        lex_basis = value_for_column(row, lex_col) if lex_col is not None else None
        lex = f"{ds}:lexeme:{escape_key_part(lex_basis or local_id or rkey)}"
        nodes["Lexeme"].append(GraphRow("Lexeme", lex, {"key": lex, "lemma": form_value,
                                                        "identity_basis": "source_local_id" if lex_basis else "row",
                                                        "homonym_no": _tv(table, row, "homonymNumber"),
                                                        **ctx.props(rkey, display, lex_basis or local_id)}))
        rels.append(ctx.rel(rkey, "Lexeme", lex, "HAS_FORM", "Form", key, "generic-form-has-form-v1", idx)); idx += 1
        language_id = _tv(table, row, "languageReference")
        if language_id:
            lang = ctx.lookup("languages", language_id) or ctx.fallback("languages", "Languoid", language_id, rkey, "Language")
            if lang.nodes and lang.nodes[0].props.get("unresolved_reference"):
                _emit(lang, nodes, rels)
            rels.append(ctx.rel(rkey, "Lexeme", lex, "USED_IN", lang.label, lang.key, "generic-form-used-in-v1", idx)); idx += 1
        parameter_id = _tv(table, row, "parameterReference")
        if parameter_id:
            concept = ctx.lookup("parameters", parameter_id) or ctx.fallback("parameters", "Concept", parameter_id, rkey, "Concept")
            if concept.nodes and concept.nodes[0].props.get("unresolved_reference"):
                _emit(concept, nodes, rels)
            local_gloss = _col(table, row, ctx.semantics.get("form_gloss_columns", DEFAULT_GLOSS_COLUMNS))
            gloss = _short(local_gloss) or concept.display
            sense = f"{ds}:sense:{escape_key_part(local_id or rkey)}"
            nodes["Sense"].append(GraphRow("Sense", sense, {"key": sense, "gloss": gloss,
                                                            "gloss_basis": "source_gloss" if local_gloss else "concept_label",
                                                            **ctx.props(rkey, gloss, parameter_id, concept.display)}))
            rels.append(ctx.rel(rkey, "Lexeme", lex, "HAS_SENSE", "Sense", sense, "generic-form-has-sense-v1", idx)); idx += 1
            rels.append(ctx.rel(rkey, "Sense", sense, "DENOTES", concept.label, concept.key, "generic-form-denotes-v1", idx)); idx += 1
    elif role == "CognateTable":
        cogset_id = _tv(table, row, "cognatesetReference")
        form_id = _tv(table, row, "formReference")
        if form_id and cogset_id:
            cogset = ctx.lookup("cognatesets", cogset_id) or ctx.fallback("cognatesets", "CognateSet", cogset_id, rkey, "Cognate set")
            if cogset.nodes and cogset.nodes[0].props.get("unresolved_reference"):
                _emit(cogset, nodes, rels)
            rels.append(ctx.rel(rkey, "Form", f"{ds}:form:{escape_key_part(form_id)}", "COGNATE_IN", "CognateSet", cogset.key,
                                "generic-cognate-in-v1", idx, doubt=_col(table, row, ["Doubt"]))); idx += 1
    elif role == "ValueTable":
        language_id = _tv(table, row, "languageReference")
        parameter_id = _tv(table, row, "parameterReference")
        value = _tv(table, row, "value")
        code_id = _tv(table, row, "codeReference")
        if language_id and parameter_id and (value not in (None, "") or code_id):
            label = ctx.semantics.get("language_table_label", "Languoid")
            lang = ctx.lookup("languages", language_id) or ctx.fallback("languages", label, language_id, rkey, label if label == "Society" else "Language")
            param = ctx.lookup("parameters", parameter_id) or ctx.fallback("parameters", "Feature", parameter_id, rkey, "Feature")
            for ent in (lang, param):
                if ent.nodes and ent.nodes[0].props.get("unresolved_reference"):
                    _emit(ent, nodes, rels)
            code = ctx.lookup("codes", code_id)
            if code is None:
                fv = f"{ds}:feature-value:{escape_key_part(parameter_id)}:{escape_key_part(value)}"
                display = _short(value if str(value) == param.display else f"{value} — {param.display}")
                nodes["FeatureValue"].append(GraphRow("FeatureValue", fv, {"key": fv, "raw_value": value, "domain": ds,
                                                                           **ctx.props(rkey, display, parameter_id, value)}))
                rels.append(ctx.rel(rkey, "FeatureValue", fv, "VALUE_OF", param.label, param.key, "code-value-of-v1", idx)); idx += 1
                code = Entity("FeatureValue", fv, display)
            rels.append(ctx.rel(rkey, lang.label, lang.key, "HAS_FEATURE_VALUE", "FeatureValue", code.key, "generic-value-feature-v1",
                                idx, value=value, feature_key=param.key)); idx += 1
    elif role == "BorrowingTable":
        local_id = _tv(table, row, "id")
        target = _tv(table, row, "targetFormReference")
        source = _tv(table, row, "sourceFormReference")
        if target and source:
            rels.append(ctx.rel(rkey, "Form", f"{ds}:form:{escape_key_part(target)}", "BORROWED_FROM", "Form",
                                f"{ds}:form:{escape_key_part(source)}", "generic-borrowed-from-v1", idx)); idx += 1
        elif target:
            word = _col(table, row, ["Source_word"])
            donor = _col(table, row, ["Source_languoid"])
            donor_code = _tv(table, row, "glottocode")
            display = _short("← " + " ".join(p for p in [word or "?", f"({donor})" if donor else None] if p))
            key = f"{ds}:borrowing:{escape_key_part(local_id or rkey)}"
            ent = Entity("BorrowingEvent", key, display)
            ent.nodes.append(GraphRow("BorrowingEvent", key, {
                "key": key, "source_word": word, "source_meaning": _col(table, row, ["Source_meaning"]),
                "donor_languoid": donor, "donor_glottocode": donor_code, "certain": _col(table, row, ["Source_certain"]),
                "relation": _col(table, row, ["Source_relation"]), **ctx.props(rkey, display, local_id, word, donor)}))
            ent.rels.append(ctx.rel(rkey, "Form", f"{ds}:form:{escape_key_part(target)}", "HAS_BORROWING", "BorrowingEvent", key,
                                    "generic-borrowing-event-v1", idx)); idx += 1
            if donor_code:
                eid = f"glottolog:glottocode|{donor_code}"
                ent.nodes.append(GraphRow("ExternalIdentifier", eid, {"key": eid, "scheme": "glottolog:glottocode", "value": donor_code,
                                                                      "display_name": donor_code, "authority": "glottolog"}))
                ent.rels.append(ctx.rel(rkey, "BorrowingEvent", key, "DONOR_LANGUAGE", "ExternalIdentifier", eid, "borrowing-donor-v1", idx)); idx += 1
            _emit(ent, nodes, rels)
    elif role == "ConcepticonConceptSet":
        cid = row.get("ID")
        if cid:
            gloss = row.get("GLOSS") or cid
            key = f"concepticon:{cid}"
            ent = Entity("Concept", key, gloss)
            ent.nodes.append(GraphRow("Concept", key, {
                "key": key, "label": gloss, "concepticon_id": cid, "concepticon_gloss": gloss,
                "semantic_field": row.get("SEMANTICFIELD") or None, "definition": row.get("DEFINITION") or None,
                "ontological_category": row.get("ONTOLOGICAL_CATEGORY") or None,
                "replacement_id": row.get("REPLACEMENT_ID") or None, **ctx.props(rkey, gloss, cid)}))
            ctx.external_id(ent, rkey, "concepticon:conceptset", cid, "concepticon-conceptset-v1")
            _emit(ent, nodes, rels)
    elif role == "ConcepticonRelation":
        src, tgt, relation = row.get("SOURCE"), row.get("TARGET"), row.get("RELATION")
        if src and tgt and relation:
            rels.append(ctx.rel(rkey, "Concept", f"concepticon:{src}", "CONCEPT_RELATION", "Concept", f"concepticon:{tgt}",
                                "concepticon-relation-v1", idx, relation=relation)); idx += 1
    elif role in CLTS_ROLES:
        idx = _clts_record(ctx, role, row, rkey, nodes, rels)
    return idx


# -- CLTS (non-CLDF CSVW tables; roles assigned by the profile) ------------------------

CLTS_SYSTEM_KINDS = {"ts": "transcription system", "td": "transcription data", "sc": "sound classes"}
CLTS_ROLES = {"CltsSource", "CltsFeature", "CltsSound", "CltsGrapheme"}


def _clts_record(ctx: DatasetContext, role: str, row: dict[str, str], rkey: str,
                 nodes: dict[str, list[GraphRow]], rels: list[RelRow]) -> int:
    ds = ctx.dataset_id
    idx = 0
    if role == "CltsSource" and row.get("NAME"):
        name = row["NAME"]
        key = f"{ds}:system:{escape_key_part(name)}"
        kind = CLTS_SYSTEM_KINDS.get(row.get("TYPE") or "", row.get("TYPE") or None)
        nodes["TranscriptionSystem"].append(GraphRow("TranscriptionSystem", key, {
            "key": key, "name": name, "kind": kind, "description": row.get("DESCRIPTION") or None,
            "refs": row.get("REFS") or None, "uri_template": row.get("URITEMPLATE") or None,
            **ctx.props(rkey, name, name, kind)}))
    elif role == "CltsFeature" and row.get("ID"):
        stype, feature, value = row.get("TYPE") or "", row.get("FEATURE") or "", row.get("VALUE") or ""
        fkey = f"{ds}:feature:{escape_key_part(stype)}:{escape_key_part(feature)}"
        fdisplay = f"{feature.replace('_', ' ')} ({stype})"
        if fkey not in ctx.owned:
            ctx.owned.add(fkey)
            nodes["Feature"].append(GraphRow("Feature", fkey, {"key": fkey, "sound_type": stype, "feature": feature,
                                                               **ctx.props(rkey, fdisplay, f"{stype}_{feature}")}))
        key = f"{ds}:feature-value:{escape_key_part(row['ID'])}"
        display = f"{value} — {fdisplay}"
        nodes["FeatureValue"].append(GraphRow("FeatureValue", key, {"key": key, "raw_value": value, "domain": ds,
                                                                    **ctx.props(rkey, display, row["ID"], value)}))
        rels.append(ctx.rel(rkey, "FeatureValue", key, "VALUE_OF", "Feature", fkey, "clts-feature-value-of-v1", idx)); idx += 1
    elif role == "CltsSound" and row.get("ID"):
        key = f"{ds}:sound:{escape_key_part(row['ID'])}"
        symbol = row.get("GRAPHEME") or None
        name = row.get("NAME") or None
        nodes["Sound"].append(GraphRow("Sound", key, {
            "key": key, "symbol": symbol, "name": name, "system": "bipa", "sound_type": row.get("TYPE") or None,
            "unicode": row.get("UNICODE") or None, "generated": row.get("GENERATED") == "+",
            "note": row.get("NOTE") or None, **ctx.props(rkey, symbol or name, row["ID"], name)}))
        for fid in (row.get("FEATURES") or "").split():
            rels.append(ctx.rel(rkey, "Sound", key, "HAS_FEATURE_VALUE", "FeatureValue",
                                f"{ds}:feature-value:{escape_key_part(fid)}", "clts-sound-feature-v1", idx)); idx += 1
    elif role == "CltsGrapheme" and row.get("PK"):
        key = f"{ds}:grapheme:{escape_key_part(row['PK'])}"
        symbol, system, name = row.get("GRAPHEME") or "", row.get("DATASET") or "", row.get("NAME") or ""
        display = _short(f"{symbol} · {system}") if system else _short(symbol) or f"Grapheme · {row['PK']}"
        nodes["Grapheme"].append(GraphRow("Grapheme", key, {
            "key": key, "symbol": symbol or None, "system": system or None, "sound_name": name or None,
            "explicit": row.get("EXPLICIT") == "+", "frequency": row.get("FREQUENCY") or None, "url": row.get("URL") or None,
            "features": row.get("FEATURES") or None, "image": row.get("IMAGE") or None, "sound_file": row.get("SOUND") or None,
            "note": row.get("NOTE") or None, **ctx.props(rkey, display, row["PK"], symbol, name)}))
        if name:
            rels.append(ctx.rel(rkey, "Grapheme", key, "REPRESENTS", "Sound",
                                f"{ds}:sound:{escape_key_part(name.replace(' ', '_'))}", "clts-grapheme-represents-v1", idx)); idx += 1
        if system:
            rels.append(ctx.rel(rkey, "Grapheme", key, "IN_SYSTEM", "TranscriptionSystem",
                                f"{ds}:system:{escape_key_part(system)}", "clts-grapheme-in-system-v1", idx)); idx += 1
    return idx
