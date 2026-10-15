"""The answer's JSON schema (the prompt's sections 3–10), strict: every field required, nothing else allowed."""
from __future__ import annotations

from typing import Any

ENTITY_KINDS = ["Lexeme", "Form", "ProtoForm", "Attestation"]
MEANING_KINDS = ["source_gloss", "contextual", "reconstructed", "semantic_component", "other"]
PROVENANCE = ["article", "article_inference", "llm_inference"]
CONFIDENCE = ["high", "medium", "low"]
CLAIM_TYPES = ["etymology", "reconstruction", "sound_change", "morphology", "semantic_change", "dating", "attestation",
               "comparison", "cognacy", "borrowing", "derivation", "analogy", "folk_etymology", "onomatopoeia",
               "source_assessment", "author_disagreement", "warning", "other"]
CLAIM_STATUSES = ["asserted", "probable", "possible", "questioned", "rejected", "uncertain", "alternative", "reported_view"]
STANCES = ["supports", "rejects", "questions", "reports", "prefers", "neutral"]
RELATION_TYPES = ["DESCENDS_FROM", "DERIVED_FROM", "BORROWED_FROM", "COGNATE_WITH", "COMPARED_WITH", "SOUND_CHANGE",
                  "REPLACES", "VARIANT_OF", "INFLUENCED_BY"]
CITATION_ROLES = ["supporting", "opposing", "discussion", "data_source", "other"]

S = {"type": "string"}
SN = {"type": ["string", "null"]}
ARR = {"type": "array", "items": S}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def _enum(values: list[str], null: bool = False) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": values + [None]} if null else {"type": "string", "enum": values}


def response_schema() -> dict[str, Any]:
    entity = _obj({
        "id": S, "kind": _enum(ENTITY_KINDS), "written": S, "canonical": SN, "language_text": SN, "language": SN, "glottocode": SN,
        "part_of_speech": SN, "morphology": {"type": "array", "items": _obj({"category": S, "value": S})},
        "lexeme_id": SN, "homonym_no": SN, "is_headword": {"type": "boolean"},
        "reconstruction": {"anyOf": [{"type": "null"}, _obj({"proto_language": SN, "level": SN})]},
        "provenance": _enum(PROVENANCE), "confidence": _enum(CONFIDENCE, True), "evidence": SN})
    meaning = _obj({"id": S, "gloss": S, "language": SN, "of": ARR, "kind": _enum(MEANING_KINDS), "concepticon_gloss": SN, "evidence": SN})
    group = _obj({"id": S, "label": S, "description": SN, "members": ARR, "evidence": SN})
    feature = _obj({"id": S, "feature": S, "value": S, "label": SN, "applies_to": ARR, "provenance": _enum(PROVENANCE),
                    "confidence": _enum(CONFIDENCE, True), "note": SN, "evidence": SN})
    claim = _obj({"id": S, "type": _enum(CLAIM_TYPES), "status": _enum(CLAIM_STATUSES), "stance": _enum(STANCES, True), "text": S,
                  "about": ARR, "supports": ARR, "contradicts": ARR, "citations": ARR, "evidence": SN})
    relation = _obj({"type": _enum(RELATION_TYPES), "from": S, "to": S, "status": _enum(CLAIM_STATUSES, True), "claims": ARR,
                     "provenance": _enum(PROVENANCE), "confidence": _enum(CONFIDENCE, True), "evidence": SN})
    citation = _obj({"id": S, "raw": S, "author": SN, "year": SN, "locator": SN, "role": _enum(CITATION_ROLES), "evidence": SN})
    note = _obj({"id": S, "title": S, "text": S, "evidence": SN})
    article = _obj({"GUID": S, "paaiskinimas": S, "entities": {"type": "array", "items": entity},
                    "meanings": {"type": "array", "items": meaning}, "meaning_groups": {"type": "array", "items": group},
                    "features": {"type": "array", "items": feature}, "claims": {"type": "array", "items": claim},
                    "relations": {"type": "array", "items": relation}, "citations": {"type": "array", "items": citation},
                    "notes": {"type": "array", "items": note}})
    return _obj({"articles": {"type": "array", "items": article}})
