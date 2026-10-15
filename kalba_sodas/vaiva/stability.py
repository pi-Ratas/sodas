"""Study „Sąvokų semantinis pastovumas“.

Two kinds of stability are kept apart, and so are their components (a single index is not built in advance):

Form – is the concept expressed by the same inherited word? (IE-CoR cognacy on the Glottolog tree)
  * retention    – share of languages whose word belongs to the concept's most widespread cognate class;
  * deep         – share of the tree's branches that keep that class (survival in distant branches);
  * replacement  – fewest cognate-class changes on the Glottolog tree (Fitch parsimony) per language.

Meaning – does the concept keep its place among other meanings? (Meaning ← Form → Meaning)
  * colex        – share of IE-CoR languages whose word for it also means another IE-CoR concept;
  * polysemy     – in how many language families DatSemShift attests polysemy with another meaning;
  * neighborhood – do different families link it to the same other meanings (mean Jaccard of partner sets);
  * spectral     – where it lies in the spectral space of the whole polysemy network, seen from each family
                   separately (the weighted mean of its partners there); small spread = stable position.

Components are then compared with each other (Spearman, principal components) and with Concepticon semantic
fields (do body parts, kinship, numerals … come out as stable by themselves?).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .spectral import laplacian_spectrum, rankdata, spearman
from .tree_fit import LANG_INFO, UNDER

STUDY = {
    "id": "semantinis-pastovumas",
    "title": "Sąvokų semantinis pastovumas",
    "summary": "Kurios sąvokos pastovios? Atskirai matuojamas formos pastovumas (ar sąvoką visur reiškia tas pats paveldėtas žodis: "
               "IE-CoR kognatai Glottolog medyje) ir reikšmės pastovumas (ar sąvoką supa tos pačios kitos reikšmės: polisemija, "
               "DatSemShift tinklo spektrinė padėtis skirtingose kalbų šeimose). Tada tikrinama, ar grafas pats iškelia kūno dalis, "
               "giminystę, skaičius. Krepšio sąvokos paryškinamos, Glottolog šaka apriboja IE-CoR kalbas; tuščias krepšys – visas grafas.",
    "accepts": ["Concept", "Languoid"],
    "basket_optional": True,
    "datasets": ["iecor", "glottolog", "concepticon", "datsemshift"],   # read in any case (bibliography: kalba_sodas.sekimas)
    "params": [
        {"name": "include_derivation", "label": "Reikšmių tinkle skaičiuoti ir derivaciją", "type": "bool", "default": False,
         "help": "DatSemShift reikšmių tinkle be polisemijos (vienas žodis – kelios reikšmės) skaičiuoti ir derivaciją (reikšmė perėjo į išvestinį žodį). Tinklas tankesnis, bet mažiau grynas."},
        {"name": "min_languages", "label": "Mažiausiai kalbų sąvokai (forma)", "type": "number", "min": 3, "max": 200, "default": 20,
         "help": "Kiek mažiausiai kalbų (turinčių vietą Glottolog medyje) turi turėti IE-CoR kognatais koduotą sąvokos žodį, kad būtų skaičiuojamas jos formos pastovumas. Rečiau paliudytos sąvokos nevertinamos."},
        {"name": "min_families", "label": "Mažiausiai šeimų sąvokai (reikšmė)", "type": "number", "min": 2, "max": 50, "default": 3,
         "help": "Iš kiek mažiausiai skirtingų kalbų šeimų turi būti paliudyti sąvokos ryšiai DatSemShift tinkle, kad būtų skaičiuojamas jos reikšmės pastovumas."},
        {"name": "dims", "label": "Spektrinės erdvės matmenys", "type": "number", "min": 2, "max": 30, "default": 10,
         "help": "Kiek pirmųjų Laplaso matricos savųjų vektorių naudoti sąvokos padėčiai reikšmių tinkle nusakyti. Mažiau – matoma tik stambi sandara; daugiau – smulkesni skirtumai, bet ir daugiau triukšmo."},
    ],
}

COMPONENTS = [
    # key, side, label, higher is more stable, short explanation
    ("retention", "forma", "Kognatų išlaikymas", True, "kalbų dalis, kurių žodis priklauso plačiausiai paplitusiai kognatų klasei"),
    ("deep", "forma", "Išlikimas tolimose šakose", True, "medžio šakų, išlaikiusių tą klasę, dalis"),
    ("replacement", "forma", "Leksinio pakeitimo dažnis", False, "mažiausias kognatų klasės pakeitimų skaičius medyje vienai kalbai"),
    ("colex", "reikšmė", "Polisemija IE-CoR", False, "kalbų dalis, kuriose tas pats žodis reiškia ir kitą IE-CoR sąvoką"),
    ("polysemy", "reikšmė", "Polisemija DatSemShift", False, "kalbų šeimų, kuriose paliudyta polisemija su kita reikšme, skaičius"),
    ("neighborhood", "reikšmė", "Kaimynystės pastovumas", True, "ar skirtingos šeimos sieja sąvoką su tomis pačiomis kitomis reikšmėmis (vid. Jaccard)"),
    ("spectral", "reikšmė", "Spektrinės padėties pastovumas", False, "sąvokos padėties spektrinėje erdvėje išsibarstymas tarp šeimų"),
]
LABEL = {k: l for k, _s, l, _u, _e in COMPONENTS}
UP = {k: u for k, _s, _l, u, _e in COMPONENTS}

COGNATES = (
    "MATCH (lex:Lexeme)-[:USED_IN]->(l:Languoid) WHERE $langs IS NULL OR l.key IN $langs "
    "MATCH (lex)-[:HAS_SENSE]->(:Sense)-[:DENOTES]->(c:Concept) WHERE c.concepticon_id IS NOT NULL "
    "MATCH (lex)-[:HAS_FORM]->(f:Form)-[:COGNATE_IN]->(cs:CognateSet) "
    "RETURN DISTINCT l.key AS lang, c.concepticon_id AS cid, cs.key AS cogset, cs.display_name AS cogname, f.value AS form"
)
CONCEPTS = ("MATCH (c:Concept) WHERE c.concepticon_id IN $ids AND c.dataset = 'concepticon' "
            "RETURN c.concepticon_id AS cid, c.display_name AS name, c.semantic_field AS field")
NETWORK = ("MATCH (c:Concept {dataset: $ds}) MATCH (rec:SourceRecord {key: c.source_record_key}) "
           "RETURN c.source_id AS id, c.concepticon_id AS cid, c.display_name AS name, rec.raw_json AS raw")


def _num(x: float | None, d: int = 2) -> str:
    return "–" if x is None else f"{x:.{d}f}".replace(".", ",")


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{round(100 * x)} %"


def _concepts(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} sąvoka"
    if 2 <= n % 10 <= 9 and not 12 <= n % 100 <= 19:
        return f"{n} sąvokos"
    return f"{n} sąvokų"


def fitch(tree_paths: dict[str, list[str]], states: dict[str, set[str]]) -> int:
    """Fewest state changes on the tree (Fitch, generalised to many children): a node takes the states found in
    most of its children and costs (children − that count). Languages are leaves under their Glottolog node."""
    children: dict[tuple, set] = defaultdict(set)
    for lang, path in tree_paths.items():
        if lang not in states:
            continue
        for d in range(1, len(path)):
            children[tuple(path[:d])].add(tuple(path[:d + 1]))
        children[tuple(path)].add(("leaf", lang))
    roots = {tuple(p[:1]) for lang, p in tree_paths.items() if lang in states}
    cost = 0

    def visit(node) -> set[str]:
        nonlocal cost
        if node[0] == "leaf":
            return states[node[1]]
        sets = [visit(c) for c in children[node]]
        if len(sets) == 1:
            return sets[0]
        count = Counter(s for st in sets for s in st)
        best = max(count.values())
        cost += len(sets) - best
        return {s for s, c in count.items() if c == best}

    for r in roots:
        visit(r)
    return cost + max(0, len(roots) - 1)


def form_stability(read: Callable[..., list[Any]], lang_keys: list[str] | None, min_langs: int,
                   progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Form components of every IE-CoR concept attested in at least ``min_langs`` languages placed in Glottolog:
    {"form": concept id → components, "paths": language → lineage keys, "names": language → name, "branches": [...]}."""
    # -- 1. form: cognate classes on the Glottolog tree --------------------------------------------------------------
    progress("Renkami IE-CoR kognatai…")
    facts = read(COGNATES, langs=lang_keys)
    cls: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))   # concept → language → classes
    words: dict[tuple[str, str], set[str]] = defaultdict(set)                      # (language, word) → concepts
    words_of: dict[tuple[str, str], set[str]] = defaultdict(set)                   # (language, concept) → words
    cogname: dict[str, str] = {}
    for r in facts:
        cid = str(r["cid"])
        cls[cid][r["lang"]].add(r["cogset"])
        cogname[r["cogset"]] = r["cogname"] or r["cogset"]
        if r["form"]:
            word = str(r["form"]).strip().lower()
            words[(r["lang"], word)].add(cid)
            words_of[(r["lang"], cid)].add(word)
    langs = sorted({l for c in cls.values() for l in c})
    info = {r["key"]: r for r in read(LANG_INFO, keys=langs)} if langs else {}
    paths = {l: list(info[l]["path_keys"]) for l in langs if info.get(l) and info[l]["path_keys"]}
    names = {l: info[l]["name"] for l in langs if info.get(l)}
    branch_of, branch_depth = _branches(paths, info)
    all_branches = sorted(set(branch_of.values()))

    form: dict[str, dict[str, Any]] = {}
    for cid, per in cls.items():
        known = {l: s for l, s in per.items() if l in paths}
        if len(known) < min_langs:
            continue
        # the most widespread class: in most branches, then in most languages
        spread = Counter()
        count = Counter()
        for l, s in known.items():
            for c in s:
                count[c] += 1
        for c in count:
            spread[c] = len({branch_of[l] for l, s in known.items() if c in s})
        dom = max(count, key=lambda c: (spread[c], count[c], c))
        branches_with = {branch_of[l] for l in known}
        changes = fitch(paths, known)
        colex = sum(1 for l in known if any(len(words[(l, wd)]) > 1 for wd in words_of[(l, cid)]))
        form[cid] = {"languages": len(known), "classes": len(count), "dominant": cogname.get(dom, dom),
                     "dominant_languages": count[dom], "retention": count[dom] / len(known),
                     "deep": spread[dom] / len(branches_with), "deep_branches": spread[dom], "branches": len(branches_with),
                     "replacement": changes / max(1, len(known) - 1), "changes": changes,
                     "colex": colex / len(known),
                     "class_list": [{"name": cogname.get(c, c), "languages": n, "branches": spread[c]} for c, n in count.most_common(8)],
                     "colex_partners": _colex_partners(words, words_of, known, cid)}

    return {"form": form, "paths": paths, "names": names, "branches": all_branches}


def polysemy_network(net_rows: list[dict[str, Any]], with_derivation: bool
                     ) -> tuple[dict[str, str | None], dict[str, str], dict[tuple[str, str], Counter]]:
    """The DatSemShift network from its concepts' source records: (DatSemShift id → Concepticon id, id → name,
    (id, id) → families attesting the link)."""
    concept_of, name_of = {}, {}
    fam_links: dict[tuple[str, str], Counter] = {}
    for r in net_rows:
        concept_of[r["id"]] = str(r["cid"]) if r["cid"] is not None else None
        name_of[r["id"]] = r["name"]
        raw = json.loads(r["raw"]) if r["raw"] else {}
        linked = raw.get("Linked_Concepts") or "[]"
        for x in (json.loads(linked) if isinstance(linked, str) else linked):
            fams = list(x.get("Polysemy_Families") or []) + (list(x.get("Derivation_Families") or []) if with_derivation else [])
            if fams:
                fam_links[tuple(sorted((r["id"], x["ID"])))] = Counter(fams)
    return concept_of, name_of, fam_links


def meaning_stability(read: Callable[..., list[Any]], with_derivation: bool, dims: int,
                      progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Meaning components of every concept of the DatSemShift polysemy network (Concepticon id → components), with
    the network's size: {"meaning", "network_concepts", "network_links", "network_component", "families"}."""
    # -- 2. meaning: the polysemy network ----------------------------------------------------------------------------
    progress("Kuriamas reikšmių tinklas (DatSemShift)…")
    net_rows = read(NETWORK, ds="datsemshift")
    concept_of, name_of, fam_links = polysemy_network(net_rows, with_derivation)
    net_nodes = sorted({a for pair in fam_links for a in pair})
    idx = {c: i for i, c in enumerate(net_nodes)}
    N = len(net_nodes)
    w = np.zeros((N, N))
    by_family: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))   # family → concept → partner → n
    for (a, b), fams in fam_links.items():
        w[idx[a], idx[b]] = w[idx[b], idx[a]] = len(fams)          # distinct families: robust to over-sampled ones
        for f, n in fams.items():
            by_family[f][a][b] += n
            by_family[f][b][a] += n
    comp = _largest(w)
    progress(f"Spektrinė reikšmių tinklo erdvė ({len(comp)} sąvokų)…")
    coords = np.full((N, dims), np.nan)
    if len(comp) > dims + 1:
        sub = w[np.ix_(comp, comp)]
        vals, vecs = laplacian_spectrum(sub)
        deg = sub.sum(1)
        emb = vecs[:, 1:dims + 1] / np.sqrt(np.where(deg > 0, deg, 1))[:, None]     # random-walk coordinates
        sample = emb[np.random.default_rng(0).choice(len(emb), size=min(400, len(emb)), replace=False)]
        scale = np.median(np.linalg.norm(sample[:, None] - sample[None], axis=-1)) or 1
        coords[comp] = emb / scale
    cid_to_ids: dict[str, list[str]] = defaultdict(list)
    for sid, cid in concept_of.items():
        if cid:
            cid_to_ids[cid].append(sid)

    meaning: dict[str, dict[str, Any]] = {}
    for cid, sids in cid_to_ids.items():
        sids = [s for s in sids if s in idx]
        if not sids:
            continue
        per_fam = defaultdict(Counter)          # family → partner → realisations
        for f, per in by_family.items():
            for s in sids:
                per_fam[f].update(per.get(s, {}))
        per_fam = {f: p for f, p in per_fam.items() if p}
        if not per_fam:
            continue
        partners = Counter()
        for f, p in per_fam.items():
            for q in p:
                partners[q] += 1               # in how many families
        sets = [set(p) for p in per_fam.values()]
        jac = [len(a & b) / len(a | b) for a, b in combinations(sets, 2)] if len(sets) > 1 else []
        positions, weights = [], []
        for f, p in per_fam.items():
            ok = [(q, n) for q, n in p.items() if np.isfinite(coords[idx[q], 0])]
            if ok:
                wt = np.array([n for _, n in ok], float)
                positions.append((coords[[idx[q] for q, _ in ok]] * wt[:, None]).sum(0) / wt.sum())
                weights.append(wt.sum())
        spread = None
        if len(positions) >= 2:
            P, W = np.array(positions), np.array(weights)
            centre = (P * W[:, None]).sum(0) / W.sum()
            spread = float((np.linalg.norm(P - centre, axis=1) * W).sum() / W.sum())
        meaning[cid] = {"families": len(per_fam), "partners": len(partners),
                        "polysemy": len(per_fam), "neighborhood": float(np.mean(jac)) if jac else None,
                        "spectral": spread, "top_partners": [{"name": name_of.get(q, q), "families": n} for q, n in partners.most_common(8)],
                        "top_families": [f for f, _ in sorted(per_fam.items(), key=lambda kv: -sum(kv[1].values()))[:6]]}

    return {"meaning": meaning, "network_concepts": N, "network_links": len(fam_links), "network_component": len(comp),
            "families": len(by_family)}


def run(read: Callable[..., list[Any]], nodes: list[dict[str, Any]], params: dict[str, Any],
        dataset_paths: dict[str, Path], progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    with_derivation = bool(params.get("include_derivation"))
    min_langs = int(params.get("min_languages") or 20)
    min_fams = int(params.get("min_families") or 3)
    dims = int(params.get("dims") or 10)

    # -- 0. basket: highlighted concepts, Glottolog scope for the IE-CoR languages --------------------------------
    focus_ids: list[str] = []
    for n in (n for n in nodes if n["label"] == "Concept"):
        rows = read("MATCH (c:Concept {key: $key}) OPTIONAL MATCH (c)-[:CORRESPONDS_TO]-(c2:Concept) "
                    "RETURN collect(DISTINCT c.concepticon_id) + collect(DISTINCT c2.concepticon_id) AS ids", key=n["key"])
        focus_ids += [str(i) for r in rows for i in r["ids"] if i is not None]
    focus_ids = sorted(set(focus_ids))
    lang_keys, scope = None, []
    for n in (n for n in nodes if n["label"] == "Languoid"):
        got = [r["key"] for r in read(UNDER, key=n["key"])] if n["key"].startswith("languoid:") else [n["key"]]
        scope.append({**n, "languages": len(got)})
        lang_keys = sorted(set((lang_keys or []) + got))

    fs = form_stability(read, lang_keys, min_langs, progress)
    form, paths, names, all_branches = fs["form"], fs["paths"], fs["names"], fs["branches"]
    ms = meaning_stability(read, with_derivation, dims, progress)
    meaning = ms["meaning"]

    # -- 3. one table: IE-CoR concepts (+ basket concepts known to the network) ------------------------------------------
    progress("Lyginami komponentai…")
    ids = sorted(set(form) | {c for c in focus_ids if c in meaning})
    if len(ids) < 5:
        raise ValueError("Per mažai sąvokų su duomenimis: sumažinkite „Mažiausiai kalbų sąvokai“ arba praplėskite krepšio šaką.")
    cinfo = {str(r["cid"]): r for r in read(CONCEPTS, ids=ids)}
    rows = []
    for cid in ids:
        f, m = form.get(cid, {}), meaning.get(cid, {})
        if m and m["families"] < min_fams:
            m = {**m, "neighborhood": None, "spectral": None}
        rows.append({"cid": cid, "name": (cinfo.get(cid) or {}).get("name") or cid, "field": (cinfo.get(cid) or {}).get("field") or "—",
                     "focus": cid in focus_ids, "form": f or None, "meaning": m or None,
                     "values": {"retention": f.get("retention"), "deep": f.get("deep"), "replacement": f.get("replacement"),
                                "colex": f.get("colex"), "polysemy": m.get("polysemy") if m else None,
                                "neighborhood": m.get("neighborhood") if m else None, "spectral": m.get("spectral") if m else None}})
    # stability percentiles per component (1 = most stable), so all components point the same way
    for key in LABEL:
        have = [r for r in rows if r["values"][key] is not None]
        if len(have) < 2:
            continue
        v = np.array([r["values"][key] for r in have], float)
        rk = rankdata(v if UP[key] else -v)
        for r, x in zip(have, rk):
            r.setdefault("pct", {})[key] = round(float((x - 1) / (len(have) - 1)), 4)
    for r in rows:
        r.setdefault("pct", {})

    # -- 4. do the components tell the same story? -------------------------------------------------------------------
    keys = [k for k in LABEL if sum(1 for r in rows if k in r["pct"]) >= 5]
    # do the meaning components merely count how much DatSemShift studied a concept? (polysemy does by definition)
    bias = {}
    for k in ("neighborhood", "spectral"):
        have = [r for r in rows if r["meaning"] and r["values"][k] is not None]
        if len(have) >= 5:
            b = spearman(np.array([r["meaning"]["families"] for r in have], float), np.array([r["values"][k] for r in have], float))
            bias[k] = round(b, 3) if b is not None else None
    corr = [[_corr(rows, a, b) for b in keys] for a in keys]
    pca = _pca(rows, keys)

    # -- 5. semantic fields: do body parts, kinship, numbers come out as stable by themselves? ---------------------------
    fields = _field_tests(rows, keys)

    result = {
        "study": STUDY["id"], "title": STUDY["title"],
        "input": {"scope": scope, "focus": focus_ids},
        "params": {"include_derivation": with_derivation, "min_languages": min_langs, "min_families": min_fams, "dims": dims},
        "components": [{"key": k, "side": s, "label": l, "up": u, "explain": e} for k, s, l, u, e in COMPONENTS],
        "summary": {"concepts": len(rows), "with_form": sum(1 for r in rows if r["form"]), "with_meaning": sum(1 for r in rows if r["meaning"]),
                    "languages": len(paths), "branches": len(all_branches), "network_concepts": ms["network_concepts"],
                    "network_links": ms["network_links"], "network_component": ms["network_component"], "families": ms["families"], "focus": sum(1 for r in rows if r["focus"])},
        "concepts": rows, "keys": keys, "corr": corr, "pca": pca, "fields": fields, "bias": bias,
        "branches": all_branches, "language_names": {l: names.get(l, l) for l in paths},
    }
    result["findings"] = findings(result)
    return result


def _colex_partners(words, words_of, known, cid) -> list[list[Any]]:
    """Other concepts the same word means, and in how many languages."""
    partners = Counter()
    for lang in known:
        for c in {c for wd in words_of[(lang, cid)] for c in words[(lang, wd)]} - {cid}:
            partners[c] += 1
    return [[c, n] for c, n in partners.most_common(6)]


def _branches(paths: dict[str, list[str]], info) -> tuple[dict[str, str], int]:
    """Branch of every language: as in tree_fit, the first level under the common ancestor with 3 … n/2 clades."""
    if not paths:
        return {}, 0
    ps = list(paths.values())
    d0 = 0
    while all(len(p) > d0 + 1 for p in ps) and len({p[d0 + 1] for p in ps}) == 1:
        d0 += 1
    at = lambda lv: len({p[min(lv, len(p) - 1)] for p in ps})
    depths = range(d0 + 1, max(len(p) for p in ps))
    lv = next((x for x in depths if 3 <= at(x) <= len(ps) / 2), next((x for x in depths if at(x) >= 2), d0 + 1))
    out = {}
    for l, p in paths.items():
        names = info[l]["path_names"]
        out[l] = names[min(lv, len(names) - 1)]
    return out, lv


def _largest(w: np.ndarray) -> list[int]:
    n, seen, best = len(w), set(), []
    nb = [np.flatnonzero(w[i] > 0) for i in range(n)]
    for s in range(n):
        if s in seen or not len(nb[s]):
            continue
        comp, stack = {s}, [s]
        while stack:
            v = stack.pop()
            for u in nb[v]:
                if int(u) not in comp:
                    comp.add(int(u))
                    stack.append(int(u))
        seen |= comp
        if len(comp) > len(best):
            best = sorted(comp)
    return best


def _corr(rows, a, b) -> float | None:
    both = [r for r in rows if a in r["pct"] and b in r["pct"]]
    if len(both) < 5:
        return None
    r = spearman(np.array([x["pct"][a] for x in both]), np.array([x["pct"][b] for x in both]))
    return round(r, 3) if r is not None else None


def _pca(rows, keys) -> dict[str, Any] | None:
    full = [r for r in rows if all(k in r["pct"] for k in keys)]
    if len(full) < max(8, len(keys) + 2) or len(keys) < 2:
        return None
    x = np.array([[r["pct"][k] for k in keys] for r in full])
    x = (x - x.mean(0)) / np.where(x.std(0) > 0, x.std(0), 1)
    vals, vecs = np.linalg.eigh(np.cov(x.T))
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    load = vecs[:, 0] * (1 if vecs[:, 0].sum() >= 0 else -1)
    scores = x @ load
    top = [full[i]["cid"] for i in np.argsort(scores)[::-1][:12]]
    return {"explained": [round(float(v / vals.sum()), 3) for v in vals], "loadings": [round(float(v), 3) for v in load],
            "concepts": len(full), "top": top, "same_sign": bool(np.all(load > 0.1) or np.all(load < -0.1))}


def _field_tests(rows, keys, perms: int = 2000) -> list[dict[str, Any]]:
    rng = np.random.default_rng(0)
    by_field = defaultdict(list)
    for r in rows:
        by_field[r["field"]].append(r)
    out = []
    for field, members in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
        if len(members) < 3:
            continue
        entry = {"field": field, "concepts": len(members), "names": [m["name"] for m in members], "tests": {}}
        for k in keys:
            vals = np.array([r["pct"][k] for r in rows if k in r["pct"]])
            mine = np.array([m["pct"][k] for m in members if k in m["pct"]])
            if len(mine) < 3 or len(vals) <= len(mine):
                continue
            obs = float(mine.mean())
            null = np.array([rng.choice(vals, size=len(mine), replace=False).mean() for _ in range(perms)])
            p_hi = (np.sum(null >= obs) + 1) / (perms + 1)
            p_lo = (np.sum(null <= obs) + 1) / (perms + 1)
            entry["tests"][k] = {"mean": round(obs, 3), "n": int(len(mine)), "p_stable": round(float(p_hi), 4), "p_mobile": round(float(p_lo), 4)}
        out.append(entry)
    return out


def findings(r: dict[str, Any]) -> list[dict[str, Any]]:
    s, rows = r["summary"], r["concepts"]
    byid = {x["cid"]: x for x in rows}
    out = []
    out.append({"id": "coverage", "title": f"Ištirta {_concepts(s['concepts'])}",
                "text": f"Formos pastovumas – {s['with_form']} IE-CoR sąvokų {s['languages']} kalbose ({s['branches']} Glottolog šakos). "
                        f"Reikšmės pastovumas – {s['with_meaning']} iš jų rastos DatSemShift tinkle ({s['network_concepts']} sąvokų, {s['network_links']} "
                        f"polisemijos porų, {s['families']} kalbų šeimos; spektrinė erdvė – didžiausia susieta dalis, {s['network_component']} sąvokų). "
                        "DatSemShift pateikia tik rastus poslinkius, o ne visas tirtas kalbas, todėl polisemijos skaičiai rodo, kiek sąvoka tyrinėta "
                        "ir kiek ji „judri“ kartu – tai svarbu vertinant polisemijos komponentą."})
    for key, side, label, up, explain in COMPONENTS:
        have = sorted((x for x in rows if key in x["pct"]), key=lambda x: -x["pct"][key])
        if len(have) < 5:
            continue
        best, worst = have[:6], have[-6:][::-1]
        tied = sum(1 for x in have if x["values"][key] == have[0]["values"][key])
        tie_txt = f" (iš viso {_concepts(tied)} su ta pačia geriausia reikšme {_num(have[0]['values'][key])}; jų tvarka atsitiktinė)" if tied > 6 else ""
        out.append({"id": f"comp-{key}", "component": key, "title": f"{label}: pastoviausios – {', '.join(x['name'] for x in best[:4])}",
                    "text": f"{explain[0].upper() + explain[1:]}. Pastoviausios: {', '.join(x['name'] for x in best)}{tie_txt}. "
                            f"Judriausios: {', '.join(x['name'] for x in worst)}."})
    keys, corr = r["keys"], r["corr"]
    form_keys = [k for k in keys if k in ("retention", "deep", "replacement")]
    mean_keys = [k for k in keys if k not in form_keys]
    cross = [corr[keys.index(a)][keys.index(b)] for a in form_keys for b in mean_keys if corr[keys.index(a)][keys.index(b)] is not None]
    inner_f = [corr[keys.index(a)][keys.index(b)] for a, b in combinations(form_keys, 2) if corr[keys.index(a)][keys.index(b)] is not None]
    out.append({"id": "twokinds", "title": "Formos ir reikšmės pastovumas – " + ("skirtingi dalykai" if cross and abs(np.mean(cross)) < 0.3 else "susiję"),
                "text": (f"Formos komponentai tarpusavyje koreliuoja vidutiniškai ρ {_num(float(np.mean(inner_f)))}, " if inner_f else "")
                        + (f"o su reikšmės komponentais – ρ {_num(float(np.mean(cross)))}. " if cross else "")
                        + "Tai patvirtina, kad „pastovi sąvoka“ ir „pastovus žodis“ nėra tas pats: sąvoka gali išlaikyti vietą tarp kitų reikšmių, "
                          "nors kalbos ją vadina vis kitais žodžiais, ir atvirkščiai."})
    quad = _quadrants(rows)
    if quad:
        out.append({"id": "quadrants", "title": "Keturios sąvokų rūšys",
                    "text": "Pastovi ir forma, ir reikšmė: " + ", ".join(quad["both"][:6]) + ". "
                            + "Pastovi reikšmė, bet žodis keičiamas: " + ", ".join(quad["meaning"][:6]) + ". "
                            + "Žodis išlieka, bet reikšmė judri: " + ", ".join(quad["form"][:6]) + ". "
                            + "Judru abu: " + ", ".join(quad["none"][:6]) + ". (Formai – pakeitimų dažnis, reikšmei – spektrinė padėtis; "
                            + "grafike kairėje ašis galima pakeisti.)"})
    pca = r["pca"]
    if pca:
        pc1 = pca["explained"][0]
        ok = pc1 >= 0.5 and pca["same_sign"]
        out.append({"id": "index", "title": f"Ar jungti į vieną indeksą? {'Galima' if ok else 'Kol kas ne'} (1-oji komponentė paaiškina {_pct(pc1)})",
                    "text": "Pagrindinių komponenčių analizė ieško vienos krypties, kuria kinta visi komponentai kartu. "
                            + (f"Ji paaiškina {_pct(pc1)} bendros įvairovės, o visi komponentai į ją įeina ta pačia kryptimi – "
                               "bendras pastovumo indeksas būtų pagrįstas. " if ok else
                               f"Ji paaiškina tik {_pct(pc1)} įvairovės"
                               + (" ir komponentai į ją įeina skirtingomis kryptimis" if not pca["same_sign"] else "")
                               + " – vienas indeksas paslėptų, kad komponentai matuoja skirtingus dalykus. ")
                            + "Sąvokos toliausiai šia kryptimi: " + ", ".join(byid[c]["name"] for c in pca["top"][:8]) + "."})
    stable, mobile = [], []
    for f in r["fields"]:
        for k, t in f["tests"].items():
            if t["p_stable"] < 0.05:
                stable.append((t["p_stable"], f["field"], k, t["mean"]))
            if t["p_mobile"] < 0.05:
                mobile.append((t["p_mobile"], f["field"], k, t["mean"]))
    stable.sort()
    mobile.sort()
    out.append({"id": "fields", "title": "Ar grafas pats iškelia pastovias sąvokų grupes?",
                "text": "Kiekvienam Concepticon semantiniam laukui tikrinta, ar jo sąvokos pastovesnės (ar judresnės) nei atsitiktinė tiek pat sąvokų imtis "
                        "(2000 atsitiktinių imčių). "
                        + ("Reikšmingai pastovesnės: " + "; ".join(f"{f} – {LABEL[k].lower()} (vid. procentilis {_pct(m)}, p = {_num(p, 3)})" for p, f, k, m in stable[:6]) + ". "
                           if stable else "Nė vienas laukas reikšmingai neišsiskiria pastovumu. ")
                        + ("Reikšmingai judresnės: " + "; ".join(f"{f} – {LABEL[k].lower()} (p = {_num(p, 3)})" for p, f, k, m in mobile[:4]) + ". " if mobile else "")
                        + "Lauką su maža p galima laikyti grafo „iškeltu“; tikrinant daug laukų ir komponentų, pavieniai p < 0,05 gali būti ir atsitiktiniai."})
    focus = [x for x in rows if x["focus"]]
    for x in focus[:12]:
        parts = [f"{LABEL[k].lower()} {_pct(x['pct'][k])}" for k in LABEL if k in x["pct"]]
        f, m = x["form"] or {}, x["meaning"] or {}
        out.append({"id": f"focus-{x['cid']}", "focus": x["cid"], "title": f"Krepšyje: {x['name']} ({x['field']})",
                    "text": "Pastovumo procentiliai (100 % – pastoviausia iš tirtų): " + ", ".join(parts) + ". "
                            + (f"Plačiausia kognatų klasė „{f['dominant']}“ – {f['dominant_languages']} iš {f['languages']} kalbų, {f['deep_branches']} iš "
                               f"{f['branches']} šakų; medyje bent {f['changes']} pakeitimai. " if f else "IE-CoR šios sąvokos neturi. ")
                            + (f"DatSemShift: polisemija {m['families']} šeimose, dažniausi kaimynai – "
                               + ", ".join(f"{p['name']} ({p['families']})" for p in m["top_partners"][:5]) + "." if m else "DatSemShift šios sąvokos neturi.")})
    out.append({"id": "method", "title": "Kaip tai apskaičiuota",
                "text": "Forma: kiekvienai sąvokai plačiausiai paplitusi IE-CoR kognatų klasė (daugiausia šakų, tada kalbų); išlikimas – jos kalbų ir šakų dalis; "
                        "pakeitimai – mažiausias klasės pasikeitimų skaičius Glottolog medyje (Fitch parsimonija, kelios klasės vienoje kalboje leidžiamos), "
                        "padalytas iš kalbų skaičiaus. Reikšmė: DatSemShift polisemijos ryšiai su kalbų šeimomis; bendras tinklas (svoris – šeimų skaičius) "
                        "išskleidžiamas normalizuoto Laplaso savaisiais vektoriais; kiekvienai šeimai sąvokos padėtis – jos tos šeimos kaimynų padėčių vidurkis, "
                        "pastovumas – šių padėčių išsibarstymas. Visi komponentai paverčiami procentiliais (100 % – pastoviausia), bet nesujungiami. "
                        + (f"Patikra: kaimynystės ir spektrinio komponento ryšys su tuo, keliose šeimose sąvoka apskritai paliudyta, yra "
                           f"ρ {_num(r['bias'].get('neighborhood'))} ir {_num(r['bias'].get('spectral'))} – "
                           + ("jie nematuoja vien tyrinėtumo." if all(abs(v or 0) < 0.3 for v in r["bias"].values()) else
                              "atsargiai: dalį skirtumų gali lemti tai, kiek sąvoka tyrinėta.") if r.get("bias") else "")})
    return out


def _quadrants(rows) -> dict[str, list[str]] | None:
    both = [x for x in rows if "replacement" in x["pct"] and "spectral" in x["pct"]]
    if len(both) < 8:
        return None
    q = {"both": [], "meaning": [], "form": [], "none": []}
    for x in sorted(both, key=lambda x: -(x["pct"]["replacement"] + x["pct"]["spectral"])):
        f, m = x["pct"]["replacement"] >= .5, x["pct"]["spectral"] >= .5
        q["both" if f and m else "meaning" if m else "form" if f else "none"].append(x["name"])
    q["none"] = q["none"][::-1]
    q["meaning"].sort(key=lambda n: next(-(x["pct"]["spectral"] - x["pct"]["replacement"]) for x in both if x["name"] == n))
    q["form"].sort(key=lambda n: next(-(x["pct"]["replacement"] - x["pct"]["spectral"]) for x in both if x["name"] == n))
    return q
