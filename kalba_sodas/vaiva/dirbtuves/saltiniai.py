"""Sources: the basket and the units taken from the graph (forms, languages, concepts, the polysemy network)."""
from __future__ import annotations

import json
from collections import Counter

import numpy as np

from .. import sound_clusters, stability, tree_fit
from .core import Basket, Graph, Items, Param, Port, part

LANG_INFO = tree_fit.LANG_INFO


def _float(x) -> float | None:
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _language_attrs(read, lang_keys: list[str]) -> dict[str, dict]:
    """Glottolog place and coordinates of languages: key → attributes of a unit."""
    out = {}
    for r in read(LANG_INFO, keys=lang_keys) if lang_keys else []:
        out[r["key"]] = {"glottolog_name": r["glottolog_name"], "lat": _float(r["lat"]), "lon": _float(r["lon"]),
                         "_glottolog": r["glottolog"], "_path": list(r["path_keys"] or []), "_path_names": list(r["path_names"] or [])}
    return out


@part("krepsys", "Šaltiniai", title="Krepšys",
      summary="Šios kortelės sodo krepšio mazgai (sode: dešinys klavišas → „Pridėk į krepšį“).",
      outputs=[Port("krepsys", ("basket",))],
      help="Krepšys pats nieko netiria: jis nurodo šaltiniams, ką imti. Prie Vaivos kairėje galite atžymėti mazgus, "
           "kurių šįkart nenorite.")
def krepsys(ctx, inputs, params):
    return {"krepsys": Basket([{k: n.get(k) for k in ("label", "key", "display_name")} for n in ctx.nodes])}


@part("formos", "Šaltiniai", title="Formos",
      summary="Krepšio sąvokų (ir per CORRESPONDS_TO susietų), reikšmių, leksemų, kognatų grupių formos arba pačios formos.",
      inputs=[Port("krepsys", ("basket",))],
      outputs=[Port("formos", ("items",), label="Formos")],
      params=[Param("max_forms", "Daugiausia formų", default=600, min=3, max=3000,
                    help="Kiek daugiausia formų paimti iš krepšio mazgų; kitos praleidžiamos (apie tai pranešama). "
                         "Garsinis atstumas lygina visas formų poras, tad darbo daugėja kvadratu.")],
      help="Sąvokai formos randamos per Sense → Lexeme → Form. Kiekviena forma turi požymius: kalba, kognatų grupė "
           "(IE-CoR), duomenynas, rekonstruota (taip / ne), kalbos vieta Glottolog medyje ir koordinatės.")
def formos(ctx, inputs, params):
    used, ignored, keys, truncated = sound_clusters.collect_forms(ctx.read, inputs["krepsys"].nodes, params["max_forms"])
    for n in ignored:
        ctx.note(f"Krepšio mazgas „{n.get('display_name') or n.get('key')}“ ({n.get('label')}) formų neturi – praleistas.")
    if truncated:
        ctx.note(f"Dėl ribos neimta dar {truncated} formų.")
    if not keys:
        raise ValueError("Krepšyje nėra formų: įdėkite sąvoką, reikšmę, leksemą, kognatų grupę ar formas.")
    rows = {r["key"]: r for r in ctx.read(sound_clusters.FORM_DETAILS, keys=keys)}
    langs = _language_attrs(ctx.read, sorted({r["lang_key"] for r in rows.values() if r["lang_key"]}))
    out = []
    for key in keys:
        r = rows.get(key)
        if r is None:
            continue
        cogs = [c for c in r["cognates"] if c.get("key")]
        written = r["written"] or ""
        out.append({"key": key, "name": r["name"], "language": r["lang"], "cognate": cogs[0]["name"] if cogs else None,
                    "dataset": r["dataset"], "reconstructed": "taip" if written.strip().startswith("*") else "ne",
                    **langs.get(r["lang_key"], {}),
                    "_label": "Form", "_language_key": r["lang_key"], "_cognate_key": cogs[0]["key"] if cogs else None,
                    "_segments": r["segments"], "_raw": json.loads(r["raw"]) if r["raw"] else {}, "_written": r["written"]})
    return {"formos": Items("forma", out, {"used": used})}


@part("kalbos", "Šaltiniai", title="Kalbos",
      summary="Kalbos su IE-CoR kognatais koduotomis reikšmėmis. Krepšyje: Glottolog šeima ar šaka, kalbos, sąvokos "
              "(apriboja reikšmes); be krepšio – visos tokios kalbos.",
      inputs=[Port("krepsys", ("basket",), optional=True)],
      outputs=[Port("kalbos", ("items",), label="Kalbos")],
      help="Kalba be Glottolog atitikmens neįtraukiama (jos vietos medyje nežinome). Požymiai: Glottolog vardas, "
           "koordinatės, koduotų reikšmių skaičius.")
def kalbos(ctx, inputs, params):
    nodes = inputs["krepsys"].nodes if "krepsys" in inputs else []
    scope, concepts, lang_keys, meaning_ids = tree_fit.basket_scope(ctx.read, nodes)
    if meaning_ids:
        ctx.note(f"Reikšmės apribotos krepšio sąvokomis ({len(meaning_ids)} Concepticon sąvokos).")
    per_lang, glosses, langs, excluded = tree_fit.language_data(ctx.read, lang_keys, meaning_ids)
    for e in excluded:
        ctx.drop(e, e["reason"], e["detail"])
    rows = [{"key": l["key"], "name": l["name"], "dataset": l["dataset"], "glottolog_name": l["glottolog_name"],
             "lat": _float(l["lat"]), "lon": _float(l["lon"]), "meanings": l["meanings"],
             "_label": "Languoid", "_glottolog": l["glottolog"], "_path": l["path"], "_path_names": l["path_names"]} for l in langs]
    if not rows:
        raise ValueError("Nė viena kalba neturi vietos Glottolog medyje.")
    return {"kalbos": Items("kalba", rows, {"per_lang": {k: v for k, v in per_lang.items()}, "glosses": glosses})}


@part("savokos", "Šaltiniai", title="Sąvokos (IE-CoR)",
      summary="Concepticon sąvokos, kurias IE-CoR koduoja kognatais. Krepšio sąvokos pažymimos (požymis „krepšyje“), "
              "krepšio Glottolog šaka apriboja kalbas.",
      inputs=[Port("krepsys", ("basket",), optional=True)],
      outputs=[Port("savokos", ("items",), label="Sąvokos")],
      help="Požymiai: semantinis laukas (Concepticon), kalbų skaičius, krepšyje (taip / ne). Su šiomis sąvokomis dirba "
           "„Formos pastovumas“ ir „Reikšmės pastovumas“.")
def savokos(ctx, inputs, params):
    nodes = inputs["krepsys"].nodes if "krepsys" in inputs else []
    focus: set[str] = set()
    for n in (n for n in nodes if n["label"] == "Concept"):
        rows = ctx.read("MATCH (c:Concept {key: $key}) OPTIONAL MATCH (c)-[:CORRESPONDS_TO]-(c2:Concept) "
                        "RETURN collect(DISTINCT c.concepticon_id) + collect(DISTINCT c2.concepticon_id) AS ids", key=n["key"])
        focus |= {str(i) for r in rows for i in r["ids"] if i is not None}
    lang_keys = None
    for n in (n for n in nodes if n["label"] == "Languoid"):
        got = [r["key"] for r in ctx.read(tree_fit.UNDER, key=n["key"])] if n["key"].startswith("languoid:") else [n["key"]]
        lang_keys = sorted(set((lang_keys or []) + got))
    if lang_keys is not None:
        ctx.note(f"Kalbos apribotos krepšio Glottolog mazgais ({len(lang_keys)} kalbos).")
    facts = ctx.read(stability.COGNATES, langs=lang_keys)
    langs_of = Counter()
    seen = set()
    for r in facts:
        if (r["lang"], str(r["cid"])) not in seen:
            seen.add((r["lang"], str(r["cid"])))
            langs_of[str(r["cid"])] += 1
    ids = sorted(set(langs_of) | focus)
    if not ids:
        raise ValueError("Nerasta kognatais koduotų sąvokų.")
    info = {str(r["cid"]): r for r in ctx.read(stability.CONCEPTS, ids=ids)}
    rows = [{"key": cid, "name": (info.get(cid) or {}).get("name") or cid, "field": (info.get(cid) or {}).get("field") or "—",
             "languages": langs_of.get(cid, 0), "focus": "taip" if cid in focus else "ne"} for cid in ids]
    return {"savokos": Items("sąvoka", rows, {"lang_keys": lang_keys, "focus": sorted(focus)})}


@part("reiksmiu_tinklas", "Šaltiniai", title="Reikšmių tinklas (DatSemShift)",
      summary="Polisemijos tinklas: sąvokos sujungtos, jei bent vienoje kalbų šeimoje tas pats žodis reiškia abi; "
              "svoris – kiek šeimų tai paliudija.",
      outputs=[Port("tinklas", ("graph",), label="Grafas")],
      params=[Param("include_derivation", "Skaičiuoti ir derivaciją", "bool", False,
                    help="Be polisemijos (vienas žodis – kelios reikšmės) skaičiuoti ir derivaciją (reikšmė perėjo į "
                         "išvestinį žodį). Tinklas tankesnis, bet mažiau grynas.")],
      help="Sąvokos atpažįstamos pagal Concepticon numerį (jei jo nėra – pagal DatSemShift numerį), todėl tinklą galima "
           "apriboti IE-CoR sąvokomis (detalė „Apriboti pagal kitą“).")
def reiksmiu_tinklas(ctx, inputs, params):
    concept_of, name_of, fam_links = stability.polysemy_network(ctx.read(stability.NETWORK, ds="datsemshift"),
                                                                params["include_derivation"])
    key_of = {sid: (cid if cid else f"dss:{sid}") for sid, cid in concept_of.items()}
    keys = sorted({key_of.get(a, f"dss:{a}") for pair in fam_links for a in pair})
    if not keys:
        raise ValueError("DatSemShift tinklas tuščias: ar duomenynas importuotas?")
    idx = {k: i for i, k in enumerate(keys)}
    w = np.zeros((len(keys), len(keys)))
    for (a, b), fams in fam_links.items():
        i, j = idx[key_of.get(a, f"dss:{a}")], idx[key_of.get(b, f"dss:{b}")]
        if i != j:
            w[i, j] = w[j, i] = max(w[i, j], len(fams))
    names = {}
    for sid, k in key_of.items():
        names.setdefault(k, name_of.get(sid) or k)
    rows = [{"key": k, "name": names.get(k, k), "concepticon": None if k.startswith("dss:") else k} for k in keys]
    return {"tinklas": Graph(Items("sąvoka", rows), w, "polisemijos šeimų skaičius")}
