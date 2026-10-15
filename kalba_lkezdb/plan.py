"""The model's answer → a checked analysis → a graph plan in the Kalba Neo4j contract.

Every node gets ``key`` (``lkezdb:…``), ``dataset = "lkezdb"``, ``dataset_release``, ``display_name``, search fields
and ``source_record_keys`` – the LKEŽDB articles it came from. Linguistic objects, features, sources and languages
are shared by all articles (one ``Form`` „esmi“ of Old Lithuanian, one ``FeatureValue`` „athematic“), so removing a
word only takes its articles' keys away and deletes what nothing else keeps. Glottolog languoids and Concepticon
concepts are never created or changed, only pointed to, and only when they exist.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any, Callable

from kalba_import.util import escape_key_part, search_props

from .schema import CLAIM_STATUSES, CLAIM_TYPES, ENTITY_KINDS, RELATION_TYPES
from .text import cross_reference, plain

DATASET = "lkezdb"
PLAN_VERSION = "lkezdb-graph-2"   # 2: languages named in English, with a place and Glottolog link
RELEASE = "lkezdb@1"
OWN_LABELS = ["Dataset", "DatasetRelease", "SourceTable", "SourceRecord", "Entry", "Article", "Source", "Citation", "Claim",
              "Lexeme", "Form", "ProtoForm", "Attestation", "Sense", "MeaningGroup", "Feature", "FeatureValue",
              "Languoid", "ArticleNote"]
NEW_CONSTRAINT_LABELS = ["Entry", "Article", "Claim", "Citation", "MeaningGroup", "ArticleNote"]

# language name (Lithuanian, as LKEŽDB and the model write it) → Glottolog code and the English name the other
# datasets use (IE-CoR, DatSemShift: "Lithuanian", not "lietuvių"), so a language is named – and gets its flag –
# alike everywhere. A third code, if any, is where the language lies on the map when its own Glottolog node has no
# coordinates (Old Lithuanian lies where Lithuanian does). Codes are checked against Neo4j like any other.
LANGUAGES: dict[str, tuple[str | None, str] | tuple[str | None, str, str]] = {
    "lietuvių": ("lith1251", "Lithuanian"), "senoji lietuvių": ("oldl1240", "Old Lithuanian", "lith1251"),
    "žemaičių": ("samo1265", "Samogitian", "lith1251"), "latvių": ("latv1249", "Latvian"),
    "senoji latvių": ("latv1249", "Old Latvian"), "latgalių": ("latv1249", "Latgalian"),
    "prūsų": ("prus1238", "Old Prussian"), "senoji prūsų": ("prus1238", "Old Prussian"),
    "sanskritas": ("sans1269", "Sanskrit"), "sanskrito": ("sans1269", "Sanskrit"), "senoji indų": ("sans1269", "Sanskrit"),
    "vedų": ("vedi1234", "Vedic Sanskrit", "sans1269"), "avestos": ("aves1237", "Avestan"), "avestų": ("aves1237", "Avestan"),
    "hetitų": ("hitt1242", "Hittite"), "gotų": ("goth1244", "Gothic"), "lotynų": ("lati1261", "Latin"),
    "senovės graikų": ("anci1242", "Ancient Greek"), "graikų": ("anci1242", "Ancient Greek"),
    "naujųjų graikų": ("mode1248", "Modern Greek"),
    "senoji bažnytinė slavų": ("chur1257", "Old Church Slavonic"), "senoji slavų": ("chur1257", "Old Church Slavonic"),
    "bažnytinė slavų": ("chur1257", "Church Slavonic"),
    "armėnų": ("clas1249", "Classical Armenian"), "senoji armėnų": ("clas1249", "Classical Armenian"),
    "rusų": ("russ1263", "Russian"), "senoji rusų": ("oldr1238", "Old East Slavic"), "baltarusių": ("bela1254", "Belarusian"),
    "ukrainiečių": ("ukra1253", "Ukrainian"), "lenkų": ("poli1260", "Polish"), "senoji lenkų": ("poli1260", "Old Polish"),
    "čekų": ("czec1258", "Czech"), "senoji čekų": ("czec1258", "Old Czech"), "slovakų": ("slov1269", "Slovak"),
    "bulgarų": ("bulg1262", "Bulgarian"), "makedonų": ("mace1250", "Macedonian"), "slovėnų": ("slov1268", "Slovenian"),
    "serbų-kroatų": ("sout1528", "Serbo-Croatian"), "serbų": ("sout1528", "Serbo-Croatian"), "kroatų": ("sout1528", "Serbo-Croatian"),
    "aukštutinių sorbų": ("uppe1395", "Upper Sorbian"), "žemutinių sorbų": ("lowe1385", "Lower Sorbian"),
    "kašubų": ("kash1274", "Kashubian"), "polabų": ("pola1255", "Polabian"),
    "praslavų": (None, "Proto-Slavic"), "prabaltų": (None, "Proto-Baltic"), "prabaltų-praslavų": (None, "Proto-Balto-Slavic"),
    "protoslavų/protobaltų": (None, "Proto-Balto-Slavic"), "praindoeuropiečių": (None, "Proto-Indo-European"),
    "ide.": (None, "Proto-Indo-European"), "indoeuropiečių": (None, "Proto-Indo-European"),
    "vokiečių": ("stan1295", "German"), "senoji aukštutinė vokiečių": ("oldh1241", "Old High German"),
    "vidurinė aukštutinė vokiečių": ("midd1343", "Middle High German"), "anglų": ("stan1293", "English"),
    "senoji anglų": ("olde1238", "Old English"), "senoji islandų": ("oldn1244", "Old Norse"), "senoji skandinavų": ("oldn1244", "Old Norse"),
    "islandų": ("icel1247", "Icelandic"), "švedų": ("swed1254", "Swedish"), "danų": ("dani1285", "Danish"),
    "norvegų": ("norw1258", "Norwegian"), "olandų": ("dutc1256", "Dutch"), "prancūzų": ("stan1290", "French"),
    "italų": ("ital1282", "Italian"), "ispanų": ("stan1288", "Spanish"), "portugalų": ("port1283", "Portuguese"),
    "rumunų": ("roma1327", "Romanian"), "airių": ("iris1253", "Irish"), "senoji airių": ("oldi1245", "Old Irish"),
    "valų": ("wels1247", "Welsh"), "bretonų": ("bret1244", "Breton"), "oskų": ("osca1245", "Oscan"), "umbrų": ("umbr1253", "Umbrian"),
    "albanų": ("gheg1238", "Albanian"), "persų": ("west2369", "Persian"), "hindi": ("hind1269", "Hindi"), "pali": ("pali1273", "Pali"),
    "suomių": ("finn1318", "Finnish"), "estų": ("esto1258", "Estonian"), "lyvių": ("livv1244", "Livonian"),
    "vengrų": ("hung1274", "Hungarian"), "karaimų": ("kara1464", "Karaim"), "gruzinų": ("nucl1302", "Georgian"),
}
_OLD = re.compile(r"^(senosios|senųjų|senojo|senoji)\s+")


def language_entry(name: Any) -> tuple[str | None, str | None, str | None]:
    """(Glottolog code, English name, map code) of a language as LKEŽDB names it – or as the model gave it in English."""
    n = nfc(name).lower().removesuffix(" kalba").removesuffix(" k.")
    e = LANGUAGES.get(n) or LANGUAGES.get(_OLD.sub("senoji ", n))
    if e is None:
        e = next((v for v in LANGUAGES.values() if v[1].lower() == n), None)
    if e is None:
        return None, None, None
    return e[0], e[1], e[2] if len(e) > 2 else e[0]


# stable Lithuanian names for the controlled feature vocabulary (the prompt's section 6): a shared node keeps its
# name whichever article included it last
FEATURE_LT = {"inflection_class": "fleksijos tipas", "stem_class": "kamieno klasė", "ablaut_grade": "abliauto laipsnis",
              "derivation": "daryba", "stem_form": "kamieno forma", "reduplication": "reduplikacija", "verb_class": "veiksmažodžio klasė",
              "accent_paradigm": "kirčiuotė"}
VALUE_LT = {"athematic": "atematinė", "thematic": "tematinė", "semithematic": "pusiau tematinė", "a_stem": "a kamienas",
            "o_stem": "o kamienas", "i_stem": "i kamienas", "u_stem": "u kamienas", "consonant_stem": "priebalsinis kamienas",
            "e_stem": "ė kamienas", "ia_stem": "ia kamienas", "nasal_infix": "nosinis intarpas", "sta_stem": "sta kamienas",
            "e_grade": "e laipsnis", "o_grade": "o laipsnis", "zero_grade": "nulinis laipsnis", "lengthened_grade": "pailgintas laipsnis",
            "root_formation": "šakninis darinys", "suffixal": "priesaginis darinys", "prefixal": "priešdėlinis darinys",
            "compound": "dūrinys", "deverbal": "deverbatyvas", "denominal": "denominatyvas", "causative": "kauzatyvas",
            "iterative": "iteratyvas", "inchoative": "inchoatyvas", "diminutive": "deminutyvas", "strong": "stiprusis",
            "weak": "silpnasis", "reduplicated": "reduplikuotas", "primary": "pirminis", "secondary": "antrinis",
            "ap1": "1 kirčiuotė", "ap2": "2 kirčiuotė", "ap3": "3 kirčiuotė", "ap4": "4 kirčiuotė"}
CLAIM_DISPLAY = 90


def short(text: str, n: int = CLAIM_DISPLAY) -> str:
    text = " ".join(nfc(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


GENERIC_LEMMA = re.compile(r"\b(formos?|formų|klasės?|paradigm\w*|kamien\w*|fleksij\w*|veiksmažodži\w*|daiktavardži\w*)\b", re.I)


def nfc(x: Any) -> str:
    return unicodedata.normalize("NFC", str(x or "").strip())


def slug(x: Any) -> str:
    s = unicodedata.normalize("NFD", nfc(x).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w]+", "-", s).strip("-") or "nezinoma"


def snake(x: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", nfc(x).lower()).strip("_")


def rel_key(start: str, rtype: str, end: str) -> str:
    return "rel:" + hashlib.sha256(f"{DATASET}|{start}|{rtype}|{end}".encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------------------------------------------------
# 1. check and repair the answer
# ---------------------------------------------------------------------------------------------------------------------

def check(answer: dict[str, Any], expected: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Keep what is consistent, drop dangling references and pseudo-lemmas; every repair is a warning."""
    warn: list[str] = []
    arts = answer.get("articles") if isinstance(answer, dict) else None
    if not isinstance(arts, list):
        raise ValueError("Atsakyme nėra „articles“ masyvo.")
    by_guid = {}
    for a in arts:
        g = str(a.get("GUID") or "")
        if g not in expected:
            close = [e for e in expected if e.replace("-", "")[:8] == g.replace("-", "")[:8]]
            if len(close) == 1:
                warn.append(f"Straipsnio GUID „{g}“ pataisytas į „{close[0]}“.")
                g = close[0]
            else:
                warn.append(f"Atsakyme nežinomas straipsnis „{g}“ – praleistas.")
                continue
        by_guid[g] = a
    for g in expected:
        if g not in by_guid:
            warn.append(f"Modelis negrąžino straipsnio {g}.")
    out = {"articles": [_check_article(g, by_guid[g], warn) for g in expected if g in by_guid]}
    return out, warn


def _list(a, name):
    v = a.get(name)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _check_article(guid: str, a: dict[str, Any], warn: list[str]) -> dict[str, Any]:
    w = lambda m: warn.append(f"[{guid[:8]}] {m}")
    ents = []
    for e in _list(a, "entities"):
        kind = e.get("kind")
        if kind not in ENTITY_KINDS or not nfc(e.get("written")):
            w(f"objektas {e.get('id')} be tinkamo tipo ar užrašo – praleistas")
            continue
        if kind == "Lexeme" and (GENERIC_LEMMA.search(nfc(e.get("written"))) or len(nfc(e.get("written")).split()) > 2):
            w(f"„{e.get('written')}“ panašu į gramatinę klasę, o ne lemą – praleista (tokias sąvokas modeliuoti kaip features)")
            continue
        e = {**e, "written": nfc(plain(e["written"])), "morphology": [m for m in e.get("morphology") or [] if isinstance(m, dict)
                                                                     and m.get("category") and m.get("value")]}
        if e.get("provenance") == "llm_inference" and not e.get("confidence"):
            e["confidence"] = "medium"
        ents.append(e)
    ids = {e["id"] for e in ents}
    lexemes = {e["id"] for e in ents if e["kind"] == "Lexeme"}
    for e in ents:
        lid = e.get("lexeme_id")
        if lid and lid not in lexemes:
            w(f"„{e['written']}“ nurodo lemą {lid}, kurios nėra – ryšys praleistas")
            e["lexeme_id"] = None
        if e["kind"] == "Lexeme":
            e["lexeme_id"] = None
    meanings = [{**m, "of": [x for x in m.get("of") or [] if x in ids]} for m in _list(a, "meanings") if nfc(m.get("gloss"))]
    mids = {m["id"] for m in meanings}
    groups = [{**g, "members": [x for x in g.get("members") or [] if x in mids]} for g in _list(a, "meaning_groups") if nfc(g.get("label"))]
    # features: one per (feature, value, provenance); their entities joined
    feats: dict[tuple, dict] = {}
    fid_map: dict[str, str] = {}
    for f in _list(a, "features"):
        fe, va = snake(f.get("feature")), snake(f.get("value"))
        if not fe or not va:
            w(f"savybė {f.get('id')} be feature/value – praleista")
            continue
        k = (fe, va, f.get("provenance") or "article")
        if k in feats:
            feats[k]["applies_to"] = sorted(set(feats[k]["applies_to"]) | set(f.get("applies_to") or []))
            fid_map[f.get("id")] = feats[k]["id"]
            w(f"savybė {fe}={va} kartojosi – sujungta")
            continue
        feats[k] = {**f, "feature": fe, "value": va, "applies_to": [x for x in f.get("applies_to") or [] if x in ids]}
        fid_map[f.get("id")] = f.get("id")
    features = list(feats.values())
    for f in features:
        f["applies_to"] = [x for x in f["applies_to"] if x in ids]
    fids = {f["id"] for f in features}
    gids = {g["id"] for g in groups}
    cits = [c for c in _list(a, "citations") if nfc(c.get("raw"))]
    sids = {c["id"] for c in cits}
    claims = []
    for c in _list(a, "claims"):
        if not nfc(c.get("text")):
            continue
        about = []
        for x in c.get("about") or []:
            x = fid_map.get(x, x)
            if x in ids | fids | mids | gids:
                about.append(x)
            else:
                w(f"teiginys {c.get('id')} rodo į nežinomą {x}")
        claims.append({**c, "type": c.get("type") if c.get("type") in CLAIM_TYPES else "other",
                       "status": c.get("status") if c.get("status") in CLAIM_STATUSES else "uncertain",
                       "about": list(dict.fromkeys(about)), "citations": [x for x in c.get("citations") or [] if x in sids]})
    cids = {c["id"] for c in claims}
    for c in claims:
        c["supports"] = [x for x in c.get("supports") or [] if x in cids and x != c["id"]]
        c["contradicts"] = [x for x in c.get("contradicts") or [] if x in cids and x != c["id"]]
    rels, seen = [], set()
    for r in _list(a, "relations"):
        t, fr, to = r.get("type"), fid_map.get(r.get("from"), r.get("from")), fid_map.get(r.get("to"), r.get("to"))
        if t not in RELATION_TYPES:
            w(f"ryšys {t} neleistinas – praleistas")
            continue
        if fr not in ids | fids or to not in ids | fids or fr == to:
            w(f"ryšys {t} {fr}→{to} rodo į nežinomą objektą – praleistas")
            continue
        if (t, fr, to) in seen:
            w(f"ryšys {t} {fr}→{to} kartojosi – paliktas vienas")
            continue
        seen.add((t, fr, to))
        rels.append({**r, "from": fr, "to": to, "claims": [x for x in r.get("claims") or [] if x in cids]})
    return {"GUID": guid, "paaiskinimas": nfc(a.get("paaiskinimas")), "entities": ents, "meanings": meanings, "meaning_groups": groups,
            "features": features, "claims": claims, "relations": rels, "citations": cits,
            "notes": [n for n in _list(a, "notes") if nfc(n.get("title") or n.get("text"))]}


# ---------------------------------------------------------------------------------------------------------------------
# 2. the graph plan
# ---------------------------------------------------------------------------------------------------------------------

class Plan:
    def __init__(self, word: dict[str, Any]):
        self.word = word
        self.nodes: dict[str, dict[str, Any]] = {}
        self.rels: dict[str, dict[str, Any]] = {}

    def node(self, node_label: str, key: str, display: Any, record: str, *alts: Any, **props: Any) -> str:
        n = self.nodes.get(key)
        if n is None:
            flat = [x for alt in alts for x in (alt if isinstance(alt, list) else [alt]) if x not in (None, "")]
            base = {"key": key, "dataset": DATASET, "dataset_release": RELEASE, "source_record_key": record}
            base.update(search_props(nfc(display) or key, None, *flat))
            n = self.nodes[key] = {"label": node_label, "key": key, "props": base, "records": []}
        n["props"].update({k: v for k, v in props.items() if v not in (None, "", [])})
        if record not in n["records"]:
            n["records"].append(record)
        return key

    def rel(self, start: str, rtype: str, end: str, record: str, external_end: str | None = None, **props: Any) -> None:
        k = rel_key(start, rtype, end)
        r = self.rels.get(k)
        if r is None:
            r = self.rels[k] = {"type": rtype, "start": start, "end": end, "end_label": external_end, "records": [],
                                "props": {"key": k, "dataset": DATASET, "dataset_release": RELEASE}}
        for name, v in props.items():
            if v in (None, "", []):
                continue
            if name in ("claims", "evidence") and r["props"].get(name) and v != r["props"][name]:
                old = r["props"][name] if isinstance(r["props"][name], list) else [r["props"][name]]
                r["props"][name] = list(dict.fromkeys(old + (v if isinstance(v, list) else [v])))
            else:
                r["props"][name] = v
        if record not in r["records"]:
            r["records"].append(record)

    def out(self, warnings: list[str]) -> dict[str, Any]:
        nodes = [{"label": n["label"], "key": n["key"], "props": {**n["props"], "source_record_keys": n["records"]}}
                 for n in self.nodes.values()]
        labels = {n["key"]: n["label"] for n in nodes}
        rels = []
        for r in self.rels.values():
            rels.append({"type": r["type"], "start": r["start"], "start_label": labels[r["start"]], "end": r["end"],
                         "end_label": r["end_label"] or labels[r["end"]], "external": bool(r["end_label"]),
                         "props": {**r["props"], "source_record_keys": r["records"]}})
        return {"version": PLAN_VERSION, "word": self.word["GUID"], "records": sorted({x for n in self.nodes.values() for x in n["records"]}),
                "nodes": nodes, "relationships": rels, "warnings": warnings}


def record_key(article_guid: str) -> str:
    return f"{DATASET}:record:{article_guid}"


def build(word: dict[str, Any], articles: list[dict[str, Any]], analysis: dict[str, Any], store,
          read: Callable[..., list[Any]] | None, warnings: list[str]) -> dict[str, Any]:
    p = Plan(word)
    sem = {a["GUID"]: a for a in analysis["articles"]}
    entry = f"{DATASET}:entry:{word['GUID']}"
    known_codes, known_concepts = _authorities(analysis, read, warnings)
    first = record_key(articles[0]["GUID"]) if articles else f"{DATASET}:record:none"
    p.node("Dataset", DATASET, "LKEŽDB", first, title="Lietuvių kalbos etimologinio žodyno duomenų bazė")
    p.node("DatasetRelease", RELEASE, "LKEŽDB (Sodo grafas 1)", first)
    table = p.node("SourceTable", f"{DATASET}:table:straipsniai", "LKEŽDB straipsniai", first)
    p.rel(RELEASE, "RELEASE_OF", DATASET, first)
    p.rel(table, "IN_RELEASE", RELEASE, first)
    for art in articles:
        rec = record_key(art["GUID"])
        p.node("Entry", entry, word["zodis"], rec, word.get("url"), headword=word["zodis"], url=word.get("url"))
        p.node("SourceRecord", rec, f"LKEŽDB · {art.get('antraste') or word['zodis']}", rec, local_id=art["GUID"],
               raw_json=_raw(art), row_number=None)
        p.rel(rec, "IN_TABLE", table, rec)
        title = f"{art.get('antraste') or word['zodis']} · {art.get('saltinis') or art.get('metai') or 'LKEŽDB'}"
        s = sem.get(art["GUID"], {})
        akey = p.node("Article", f"{DATASET}:article:{art['GUID']}", title, rec, art.get("saltinis"),
                      headword=art.get("antraste"), gloss=art.get("reiksme"), text=plain(art.get("tekstas") or ""),
                      text_marked=art.get("tekstas"), source=art.get("saltinis"), source_title=art.get("saltinis_pilnas"),
                      year=art.get("metai"), locator=art.get("vieta_saltinyje"), paaiskinimas=s.get("paaiskinimas"))
        p.rel(entry, "HAS_ARTICLE", akey, rec)
        if art.get("saltinio_GUID"):
            src = p.node("Source", f"{DATASET}:source:{art['saltinio_GUID']}", art.get("saltinis") or art.get("saltinis_pilnas"), rec,
                         art.get("saltinis_pilnas"), short=art.get("saltinis"), title=art.get("saltinis_pilnas"))
            p.rel(akey, "HAS_SOURCE", src, rec, locator=art.get("vieta_saltinyje"), role="article_source")
        target = cross_reference(art.get("tekstas") or "")
        if target:
            tw = store.find_word(target) if store else None
            if tw:
                other = p.node("Entry", f"{DATASET}:entry:{tw['GUID']}", tw["zodis"], rec, headword=tw["zodis"], stub=True)
                p.rel(akey, "SEE_ALSO", other, rec, text=plain(art.get("tekstas")))
        if s:
            _article(p, s, akey, entry, rec, store, known_codes, known_concepts)
    return p.out(warnings)


def _raw(art: dict[str, Any]) -> str:
    import json
    return json.dumps({k: art.get(k) for k in ("GUID", "antraste", "reiksme", "tekstas", "saltinis", "saltinis_pilnas", "metai",
                                               "vieta_saltinyje")}, ensure_ascii=False, sort_keys=True)


def _authorities(analysis, read, warnings) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Which Glottolog codes and Concepticon glosses the answer names really exist (code → key, name and place;
    gloss → key)."""
    codes, glosses = set(), set()
    for a in analysis["articles"]:
        for e in a["entities"]:
            code, _name, geo = language_entry(e.get("language") or e.get("language_text"))
            for c in (code or e.get("glottocode"), geo):
                if c:
                    codes.add(nfc(c))
        for m in a["meanings"]:
            if m.get("concepticon_gloss"):
                glosses.add(nfc(m["concepticon_gloss"]).upper())
    if read is None:
        return {}, {}
    try:
        kc = {r["code"]: r for r in read("UNWIND $codes AS code MATCH (l:Languoid {key: 'languoid:' + code}) "
                                         "RETURN code, l.key AS key, coalesce(l.display_name, l.name) AS name, "
                                         "l.latitude AS latitude, l.longitude AS longitude",
                                         codes=sorted(codes))} if codes else {}
        kg = {r["gloss"]: r["key"] for r in read("MATCH (c:Concept {dataset: 'concepticon'}) WHERE c.concepticon_gloss IN $g "
                                                 "RETURN c.concepticon_gloss AS gloss, c.key AS key", g=sorted(glosses))} if glosses else {}
    except Exception as exc:  # noqa: BLE001 – Neo4j down: plan without authority links
        warnings.append(f"Glottolog / Concepticon patikrinti nepavyko ({exc}); kalbos ir sąvokos nesusietos.")
        return {}, {}
    for c in sorted(codes - set(kc)):
        warnings.append(f"Glottolog kodo „{c}“ bazėje nėra – kalba nesusieta su Glottolog.")
    for g in sorted(glosses - set(kg)):
        warnings.append(f"Concepticon glosos „{g}“ bazėje nėra – reikšmė nesusieta.")
    return kc, kg


def _languoid(p: Plan, lang_lt: str, e: dict[str, Any], rec: str, codes: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """The LKEŽDB languoid of a language (key from its Lithuanian name, as before) named like in the other datasets,
    with its place and a CORRESPONDS_TO to Glottolog. Returns (key, name the linguistic objects use)."""
    known, english, geo = language_entry(lang_lt)
    code = nfc(known or e.get("glottocode")) or None   # the curated table wins over the model
    glotto = codes.get(code) if code else None
    name = english or (glotto and glotto["name"]) or lang_lt
    place = codes.get(geo) if geo and geo != code else None
    place = place if place and place.get("latitude") is not None else glotto
    lk = p.node("Languoid", f"{DATASET}:languoid:{slug(lang_lt)}", name, rec, [lang_lt, e.get("language_text")], name=name,
                name_lt=lang_lt, latitude=place and place.get("latitude"), longitude=place and place.get("longitude"))
    # a node shared by many articles keeps the name it gets now, even if an earlier article named it otherwise
    p.nodes[lk]["props"]["display_name"] = name
    if glotto:
        p.nodes[lk]["props"]["glottocode"] = code
        p.rel(lk, "CORRESPONDS_TO", glotto["key"], rec, external_end="Languoid", basis="glottocode")
    return lk, name


def _article(p: Plan, s: dict[str, Any], akey: str, entry: str, rec: str, store, codes, concepts) -> None:
    ak = akey.rsplit(":", 1)[-1]
    local: dict[str, str] = {}
    # linguistic objects
    for e in s["entities"]:
        lang_lt = nfc(e.get("language")) or nfc(e.get("language_text")) or None
        lk, lang = _languoid(p, lang_lt, e, rec, codes) if lang_lt else (None, None)
        written = nfc(e.get("canonical")) or e["written"]
        kind = e["kind"]
        if kind == "Lexeme":
            key = f"{DATASET}:lexeme:{slug(lang_lt)}:{escape_key_part(written)}" + (f":{escape_key_part(e['homonym_no'])}" if e.get("homonym_no") else "")
        elif kind == "Form":
            key = f"{DATASET}:form:{slug(lang_lt)}:{escape_key_part(written)}"
        elif kind == "ProtoForm":
            pl = (e.get("reconstruction") or {}).get("proto_language") or lang_lt
            key = f"{DATASET}:protoform:{slug(pl)}:{escape_key_part(written)}"
        else:
            key = f"{DATASET}:attestation:{ak}:{e['id']}"
        morph = {f"morph_{snake(m['category'])}": nfc(m["value"]) for m in e.get("morphology") or []}
        rc = e.get("reconstruction") or {}
        local[e["id"]] = p.node(kind, key, e["written"], rec, [written, e.get("language_text")],
                                written=e["written"], canonical=e.get("canonical"), language=lang, language_lt=lang_lt,
                                language_text=e.get("language_text"),
                                part_of_speech=e.get("part_of_speech"), homonym_no=e.get("homonym_no"),
                                proto_language=rc.get("proto_language"), reconstruction_level=rc.get("level"),
                                provenance=e.get("provenance"), confidence=e.get("confidence"), evidence=e.get("evidence"), **morph)
        if lk:
            p.rel(local[e["id"]], "USED_IN", lk, rec)
        if e.get("is_headword"):
            p.rel(entry, "HEADWORD", local[e["id"]], rec)
    for e in s["entities"]:
        if e.get("lexeme_id"):
            p.rel(local[e["lexeme_id"]], "HAS_FORM", local[e["id"]], rec, provenance=e.get("provenance"))
    # meanings
    for m in s["meanings"]:
        key = p.node("Sense", f"{DATASET}:sense:{ak}:{m['id']}", m["gloss"], rec, m.get("concepticon_gloss"),
                     gloss=m["gloss"], language=m.get("language"), kind=m.get("kind"), concepticon_gloss=m.get("concepticon_gloss"),
                     evidence=m.get("evidence"))
        local[m["id"]] = key
        for x in m["of"]:
            p.rel(local[x], "HAS_SENSE", key, rec)
        g = nfc(m.get("concepticon_gloss")).upper()
        if g in concepts:
            p.rel(key, "DENOTES", concepts[g], rec, external_end="Concept", basis="concepticon_gloss")
    for g in s["meaning_groups"]:
        key = p.node("MeaningGroup", f"{DATASET}:group:{ak}:{g['id']}", g["label"], rec, label=g["label"],
                     description=g.get("description"), evidence=g.get("evidence"))
        local[g["id"]] = key
        for x in g["members"]:
            p.rel(local[x], "IN_MEANING_GROUP", key, rec)
    # features: one shared node per (feature, value)
    for f in s["features"]:
        feature_lt = FEATURE_LT.get(f["feature"], f["feature"].replace("_", " "))
        value_lt = VALUE_LT.get(f["value"]) or nfc(f.get("label")) or f["value"].replace("_", " ")
        fk = p.node("Feature", f"{DATASET}:feature:{f['feature']}", feature_lt, rec, f["feature"], feature=f["feature"])
        vk = p.node("FeatureValue", f"{DATASET}:feature-value:{f['feature']}:{f['value']}", f"{value_lt} ({feature_lt})",
                    rec, [f["value"], f["feature"], value_lt], feature=f["feature"], raw_value=f["value"], label=value_lt)
        p.rel(vk, "VALUE_OF", fk, rec)
        local[f["id"]] = vk
        for x in f["applies_to"]:
            p.rel(local[x], "HAS_FEATURE_VALUE", vk, rec, provenance=f.get("provenance"), confidence=f.get("confidence"),
                  evidence=f.get("evidence"), note=f.get("note"))
    # citations and claims
    for c in s["citations"]:
        key = p.node("Citation", f"{DATASET}:citation:{ak}:{c['id']}", c["raw"], rec, [c.get("author"), c.get("year")],
                     raw=c["raw"], author=c.get("author"), year=c.get("year"), locator=c.get("locator"), role=c.get("role"),
                     evidence=c.get("evidence"))
        local[c["id"]] = key
        src = store.resolve_citation(c.get("raw"), c.get("author"), c.get("year")) if store else None
        if src:
            sk = p.node("Source", f"{DATASET}:source:{src['GUID']}", src["santrumpa"], rec, src["saltinis"], short=src["santrumpa"],
                        title=src["saltinis"])
            p.rel(key, "CITES", sk, rec, locator=c.get("locator"))
    for c in s["claims"]:
        key = p.node("Claim", f"{DATASET}:claim:{ak}:{c['id']}", short(c["text"]), rec, c["text"], claim_type=c["type"], status=c["status"],
                     stance=c.get("stance"), text=c["text"], evidence=c.get("evidence"))
        local[c["id"]] = key
        p.rel(akey, "HAS_CLAIM", key, rec)
    for c in s["claims"]:
        for x in c["about"]:
            p.rel(local[c["id"]], "ABOUT", local[x], rec)
        for x in c["supports"]:
            p.rel(local[c["id"]], "SUPPORTS", local[x], rec)
        for x in c["contradicts"]:
            p.rel(local[c["id"]], "CONTRADICTS", local[x], rec)
        for x in c["citations"]:
            p.rel(local[c["id"]], "SUPPORTED_BY", local[x], rec)
    for r in s["relations"]:
        p.rel(local[r["from"]], r["type"], local[r["to"]], rec, status=r.get("status"), provenance=r.get("provenance"),
              confidence=r.get("confidence"), evidence=r.get("evidence"),
              claims=[local[x] for x in r.get("claims") or []])
    for n in s["notes"]:
        key = p.node("ArticleNote", f"{DATASET}:note:{ak}:{n['id']}", short(n.get("title") or n.get("text")), rec, title=n.get("title"),
                     text=n.get("text"), evidence=n.get("evidence"))
        p.rel(akey, "HAS_NOTE", key, rec)
    # the article reaches its objects through its claims; objects no claim reaches are „mentioned“ directly
    reached = _reached(s)
    for e in s["entities"]:
        if e["id"] not in reached and not e.get("is_headword"):
            p.rel(akey, "MENTIONS", local[e["id"]], rec)


def _reached(s: dict[str, Any]) -> set[str]:
    """Local IDs connected (either way) to something a claim is about."""
    adj: dict[str, set[str]] = defaultdict(set)

    def link(a, b):
        adj[a].add(b)
        adj[b].add(a)
    for e in s["entities"]:
        if e.get("lexeme_id"):
            link(e["id"], e["lexeme_id"])
    for m in s["meanings"]:
        for x in m["of"]:
            link(m["id"], x)
    for f in s["features"]:
        for x in f["applies_to"]:
            link(f["id"], x)
    for r in s["relations"]:
        link(r["from"], r["to"])
    todo = [x for c in s["claims"] for x in c["about"]]
    seen = set(todo)
    while todo:
        v = todo.pop()
        for u in adj[v]:
            if u not in seen:
                seen.add(u)
                todo.append(u)
    return seen
