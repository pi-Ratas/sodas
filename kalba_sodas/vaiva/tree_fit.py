"""Study „Kalbų leksinis artumas ir genealoginis medis“ (from the experiment laikina/spektras.py).

Two notions of how close two languages are:

* genealogical – the number of Glottolog tree edges between the languoids the languages correspond to;
* lexical – of the meanings (Concepticon concepts) coded in both languages, the share expressed by cognates
  (S = C / M: M comparable meanings, C of them with intersecting cognate sets; each meaning counted once).

They are compared pair by pair (Spearman ρ, Mantel permutation test), graph by graph (spectra of the lexical
graph and of the tree graph, spectral clusters against Glottolog clades at every depth) and as trees (average
linkage of the lexical distances against Glottolog branches). Neo4j is only read.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .spectral import (adjusted_rand, affinity_clusters, classical_mds, labels_for, laplacian_spectrum, mantel,
                       signed_embedding, upgma)

STUDY = {
    "id": "kalbu-medis",
    "title": "Kalbų leksinis artumas ir genealoginis medis",
    "summary": "Ar kalbos, kurios dalijasi daugiau kognatų, ir Glottolog medyje stovi arčiau? Palyginamas kiekvienos kalbų poros "
               "leksinis artumas su atstumu medyje, abiejų grafų spektrai ir grupės, leksinis medis su Glottolog šakomis; "
               "randamos medžiui prieštaraujančios kalbos ir poros. Krepšyje: Glottolog šeima ar šaka, kalbos, sąvokos "
               "(apriboja reikšmes) – arba nieko (visos kalbos su kognatų duomenimis).",
    "accepts": ["Languoid", "Concept"],
    "basket_optional": True,
    "datasets": ["glottolog", "iecor"],   # read in any case (bibliography: kalba_sodas.sekimas)
    "params": [
        {"name": "measure", "label": "Genealoginis atstumas", "type": "select", "default": "ancestor",
         "options": [["ancestor", "bendro protėvio gylis"], ["edges", "briaunų skaičius medyje (pirminis bandymas)"]],
         "help": "Kaip matuojamas dviejų kalbų atstumas Glottolog medyje. „Bendro protėvio gylis“: kuo giliau medyje yra artimiausias bendras protėvis, tuo kalbos artimesnės. „Briaunų skaičius“: kiek šakų reikia pereiti nuo vienos kalbos iki kitos – iškraipo, kai medžio šakos nevienodai smulkiai suskaidytos."},
        {"name": "min_overlap", "label": "Mažiausiai bendrų reikšmių porai", "type": "number", "min": 5, "max": 500, "default": 50,
         "hint": "menkiau paliudytos poros leksiniame grafe nejungiamos",
         "help": "Kiek mažiausiai tų pačių reikšmių (sąvokų) turi būti koduota abiem kalbom, kad pora būtų lyginama leksiniame grafe. Menkiau paliudytos poros nejungiamos; kalba be nė vienos tokios poros į tyrimą nepatenka."},
        {"name": "k", "label": "Leksinių grupių skaičius", "type": "number", "min": 2, "max": 30, "default": None,
         "hint": "tuščia – pagal savųjų reikšmių tarpą",
         "help": "Į kiek grupių skirstyti kalbas spektriniu metodu (leksiniame ir medžio grafe – po tiek pat). Tuščia – parenkama ten, kur didžiausias tarpas tarp gretimų savųjų reikšmių (2–12)."},
        {"name": "tau", "label": "Medžio svorio mastas τ", "type": "number", "min": 1, "max": 30, "default": 4,
         "hint": "medžio grafo svoris exp(−atstumas/τ)",
         "help": "Kaip greitai medžio grafe silpsta dviejų kalbų ryšys: svoris exp(−atstumas/τ). Mažas τ – jungiamos beveik vien artimiausios kalbos, didelis – ir tolimos šakos."},
        {"name": "permutations", "label": "Mantel testo perstatų", "type": "number", "min": 0, "max": 9999, "default": 999,
         "help": "Kiek kartų Mantel teste atsitiktinai sumaišyti kalbas, kad būtų įvertinta p reikšmė: ar leksinio artumo ir atstumo medyje sutapimas nėra atsitiktinis. 0 – p neskaičiuojama; 999 – p tikslumas iki 0,001; daugiau – ilgiau skaičiuojama."},
    ],
}

# lexical languoids with cognate-coded meanings: language, meaning (Concepticon id), cognate set
LEXICAL = (
    "MATCH (lex:Lexeme)-[:USED_IN]->(l:Languoid) "
    "WHERE $langs IS NULL OR l.key IN $langs "
    "MATCH (lex)-[:HAS_SENSE]->(:Sense)-[:DENOTES]->(concept:Concept) "
    "WHERE concept.concepticon_id IS NOT NULL AND ($concepts IS NULL OR concept.concepticon_id IN $concepts) "
    "MATCH (lex)-[:HAS_FORM]->(:Form)-[:COGNATE_IN]->(c:CognateSet) "
    "RETURN DISTINCT l.key AS lang, concept.concepticon_id AS meaning, head(collect(concept.display_name)) AS gloss, c.key AS cogset"
)
LANG_INFO = (
    "UNWIND $keys AS k MATCH (l:Languoid {key: k}) "
    "OPTIONAL MATCH (l)-[:IDENTIFIED_BY]->(e:ExternalIdentifier {scheme: 'glottolog:glottocode'}) "
    "OPTIONAL MATCH (l)-[:CORRESPONDS_TO]-(c:Languoid {dataset: 'glottolog'}) "
    "WITH l, coalesce(c.key, CASE WHEN l.key STARTS WITH 'languoid:' THEN l.key END, 'languoid:' + e.value) AS gk "
    "OPTIONAL MATCH (g:Languoid {key: gk}) "
    "OPTIONAL MATCH p = (top:Languoid)-[:PARENT_OF*0..]->(g) WHERE NOT ()-[:PARENT_OF]->(top) "
    "RETURN l.key AS key, l.display_name AS name, l.dataset AS dataset, l.latitude AS lat, l.longitude AS lon, g.key AS glottolog, "
    "g.display_name AS glottolog_name, [n IN nodes(p) | n.key] AS path_keys, [n IN nodes(p) | n.display_name] AS path_names"
)
# lexical languoids whose Glottolog counterpart lies under a basket Glottolog node; from each Glottolog languoid g
# outwards (its own relationships, and the identifiers with its glottocode – index ExternalIdentifier.value), not by
# pairing every languoid with every identifier (Indo-European: 10 min → 0.2 s)
UNDER = (   # the scope of a study: its rows are not data used (kalba_sodas.sekimas.SCOPE)
    "/* apimtis */ MATCH (top:Languoid {key: $key})-[:PARENT_OF*0..]->(g:Languoid) "
    "CALL (g) { MATCH (l:Languoid)-[:CORRESPONDS_TO|IDENTIFIED_BY]-(g) RETURN l "
    "UNION MATCH (x:ExternalIdentifier {value: g.glottocode})-[:CORRESPONDS_TO|IDENTIFIED_BY]-(l:Languoid) RETURN l } "
    "WITH DISTINCT l WHERE l.dataset <> 'glottolog' RETURN l.key AS key"
)

MIN_ORDERED = 100   # a language's fit is judged only when the tree orders at least this many pairs of other languages
BRANCH_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def _num(x: float | None, d: int = 2) -> str:
    return "–" if x is None else f"{x:.{d}f}".replace(".", ",")


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{round(100 * x)} %"


def _langs(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} kalba"
    if 2 <= n % 10 <= 9 and not 12 <= n % 100 <= 19:
        return f"{n} kalbos"
    return f"{n} kalbų"


def _rho_words(r: float | None) -> str:
    if r is None:
        return "neįvertinama"
    a = abs(r)
    return "labai stipri" if a >= .8 else "stipri" if a >= .6 else "vidutinė" if a >= .4 else "silpna" if a >= .2 else "beveik jokios"


def _ari_words(x: float | None) -> str:
    if x is None:
        return "–"
    return "beveik sutampa" if x >= .8 else "gerokai sutampa" if x >= .5 else "sutampa iš dalies" if x >= .2 else "beveik nesutampa"


def basket_scope(read: Callable[..., list[Any]], nodes: list[dict[str, Any]]
                 ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str] | None, list[str] | None]:
    """What the basket asks for: (Glottolog scope nodes with their language counts, concept nodes,
    language keys or None for all, Concepticon ids of the meanings or None for all)."""
    concepts = [n for n in nodes if n["label"] == "Concept"]
    meaning_ids = None
    if concepts:
        rows = read("UNWIND $keys AS k MATCH (c:Concept {key: k}) OPTIONAL MATCH (c)-[:CORRESPONDS_TO]-(c2:Concept) "
                    "RETURN collect(DISTINCT c.concepticon_id) + collect(DISTINCT c2.concepticon_id) AS ids", keys=[c["key"] for c in concepts])
        meaning_ids = sorted({str(i) for r in rows for i in r["ids"] if i is not None})
        if not meaning_ids:
            raise ValueError("Krepšio sąvokos neturi Concepticon atitikmens, todėl reikšmių apriboti negalima.")
    lang_keys: list[str] | None = None
    scope = []
    for n in (n for n in nodes if n["label"] == "Languoid"):
        if n["key"].startswith("languoid:"):          # a Glottolog family / branch / language
            got = [r["key"] for r in read(UNDER, key=n["key"])]
            scope.append({**n, "languages": len(got)})
            lang_keys = (lang_keys or []) + got
        else:
            scope.append({**n, "languages": 1})
            lang_keys = (lang_keys or []) + [n["key"]]
    if lang_keys is not None:
        lang_keys = sorted(set(lang_keys))
        if not lang_keys:
            raise ValueError("Po krepšio Glottolog mazgais nerasta kalbų su leksiniais duomenimis.")
    return scope, concepts, lang_keys, meaning_ids


def language_data(read: Callable[..., list[Any]], lang_keys: list[str] | None, meaning_ids: list[str] | None
                  ) -> tuple[dict[str, dict[str, set[str]]], dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Cognate-coded meanings of the languages: (language → meaning → cognate sets, meaning glosses,
    languages placed in Glottolog with their lineage, languages left out)."""
    facts = read(LEXICAL, langs=lang_keys, concepts=meaning_ids)
    if not facts:
        raise ValueError("Nerasta kognatais koduotų reikšmių šioms kalboms.")
    per_lang: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    glosses: dict[str, str] = {}
    for r in facts:
        per_lang[r["lang"]][str(r["meaning"])].add(r["cogset"])
        glosses.setdefault(str(r["meaning"]), r["gloss"])
    info = {r["key"]: r for r in read(LANG_INFO, keys=sorted(per_lang))}
    excluded, langs = [], []
    for key in sorted(per_lang):
        r = info.get(key)
        if r is None or not r["glottolog"] or not r["path_keys"]:
            excluded.append({"key": key, "name": (r or {}).get("name") or key, "reason": "nėra Glottolog atitikmens",
                             "detail": "Kalba nesusieta su Glottolog (CORRESPONDS_TO ar glottocode), todėl jos vietos medyje nežinome."})
            continue
        langs.append({"key": key, "name": r["name"], "dataset": r["dataset"], "glottolog": r["glottolog"], "glottolog_name": r["glottolog_name"],
                      "path": list(r["path_keys"]), "path_names": list(r["path_names"]), "meanings": len(per_lang[key]),
                      "lat": r["lat"], "lon": r["lon"]})
    return per_lang, glosses, langs, excluded


def genealogical(langs: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """Tree distances of every pair from their Glottolog lineages (``path``, ``glottolog``): (edges, ancestor depth).

    edges: tree edges between the two languoids (laikina/spektras.py); ancestor: how many levels below the family's
    root their last common ancestor is, turned into a distance (deepest shared ancestor = 0). Glottolog branches
    have very unequal numbers of intermediate nodes, so counting edges makes shallow branches look close.
    Languages of different families: NaN."""
    n = len(langs)
    edges_d = np.full((n, n), np.nan)
    shared_depth = np.full((n, n), np.nan)
    for i in range(n):
        for j in range(i, n):
            a, b = langs[i]["path"], langs[j]["path"]
            if a[0] != b[0]:
                continue
            common = next((t for t, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            edges_d[i, j] = edges_d[j, i] = len(a) + len(b) - 2 * common
            shared_depth[i, j] = shared_depth[j, i] = common
    deepest = np.nanmax(shared_depth) if n and np.isfinite(shared_depth).any() else 0
    ancestor_d = np.where(np.isfinite(shared_depth), deepest - shared_depth, np.nan)
    for i in range(n):
        for j in range(n):
            if langs[i]["glottolog"] == langs[j]["glottolog"]:
                ancestor_d[i, j] = edges_d[i, j] = 0
    return edges_d, ancestor_d


def lexical(sets: list[dict[str, set[str]]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For every pair of languages (meaning → cognate sets): meanings coded in both (M), how many of them share a
    cognate set (C), and the lexical similarity S = C/M (NaN when M = 0)."""
    n = len(sets)
    comparable = np.zeros((n, n), dtype=int)
    shared = np.zeros((n, n), dtype=int)
    sim = np.full((n, n), np.nan)
    for i in range(n):
        for j in range(i, n):
            common = sets[i].keys() & sets[j].keys()
            m = len(common)
            c = sum(1 for v in common if sets[i][v] & sets[j][v])
            comparable[i, j] = comparable[j, i] = m
            shared[i, j] = shared[j, i] = c
            if m:
                sim[i, j] = sim[j, i] = c / m
    return comparable, shared, sim


def branch_levels(paths: list[list[str]]) -> tuple[int, int]:
    """(depth of the common ancestor of all, the branch level): the first level below the ancestor with three to n/2
    clades, else the first with two – taken from the tree, not from a result, so nothing is circular."""
    depth0 = 0
    while all(len(p) > depth0 + 1 for p in paths) and len({p[depth0 + 1] for p in paths}) == 1:
        depth0 += 1
    clades_at = lambda lv: len({p[min(lv, len(p) - 1)] for p in paths})
    depths = range(depth0 + 1, max(len(p) for p in paths))
    branch_depth = next((lv for lv in depths if 3 <= clades_at(lv) <= len(paths) / 2),
                        next((lv for lv in depths if clades_at(lv) >= 2), depth0 + 1))
    return depth0, branch_depth


def run(read: Callable[..., list[Any]], nodes: list[dict[str, Any]], params: dict[str, Any],
        dataset_paths: dict[str, Path], progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    min_overlap = int(params.get("min_overlap") or 50)
    k_wanted = int(params["k"]) if params.get("k") not in (None, "", 0) else None
    tau = float(params.get("tau") or 4)
    perms = int(params.get("permutations") if params.get("permutations") is not None else 999)
    measure = params.get("measure") if params.get("measure") in ("ancestor", "edges") else "ancestor"

    # -- 1. which languages and meanings --------------------------------------------------------------------
    progress("Renkamos kalbos ir reikšmės…")
    scope, concepts, lang_keys, meaning_ids = basket_scope(read, nodes)
    per_lang, glosses, langs, excluded = language_data(read, lang_keys, meaning_ids)

    # -- 2. matrices --------------------------------------------------------------------------------------------
    progress("Skaičiuojami genealoginiai ir leksiniai atstumai…")
    n = len(langs)
    edges_d, ancestor_d = genealogical(langs)
    gen = ancestor_d if measure == "ancestor" else edges_d
    comparable, shared, sim = lexical([per_lang[l["key"]] for l in langs])

    # the lexical graph joins well attested pairs; its largest connected part is analysed
    w = np.where((comparable >= min_overlap) & np.isfinite(sim), sim, 0.0)
    np.fill_diagonal(w, 0)
    part = _largest_component(w)
    for i in range(n):
        if i not in part:
            best = int(np.max(np.where(np.arange(n) != i, comparable[i], 0))) if n > 1 else 0
            excluded.append({"key": langs[i]["key"], "name": langs[i]["name"], "reason": "per mažai bendrų reikšmių",
                             "detail": f"Su jokia kita kalba neturi bent {min_overlap} abiejose koduotų reikšmių "
                                       f"(daugiausia {best}), todėl į leksinį grafą nepatenka."})
    idx = sorted(part)
    if len(idx) < 4:
        raise ValueError(f"Leksiniame grafe tik {len(idx)} kalbos: sumažinkite „Mažiausiai bendrų reikšmių porai“.")
    langs = [langs[i] for i in idx]
    gen, comparable, shared, sim, w = gen[np.ix_(idx, idx)], comparable[np.ix_(idx, idx)], shared[np.ix_(idx, idx)], sim[np.ix_(idx, idx)], w[np.ix_(idx, idx)]
    n = len(langs)
    edges_d, ancestor_d = edges_d[np.ix_(idx, idx)], ancestor_d[np.ix_(idx, idx)]
    lexd = np.where(comparable >= min_overlap, 1 - np.nan_to_num(sim, nan=0.0), np.nan)
    np.fill_diagonal(lexd, 0)
    other = edges_d if measure == "ancestor" else ancestor_d
    rho_other, _ = mantel(other, lexd, 0)
    # the common ancestor of all, and the branch level (from the tree, not from the lexical result)
    depth0, branch_depth = branch_levels([l["path"] for l in langs])

    # -- 3. pairs: correlation and what similarity to expect at each tree distance ------------------------------
    progress("Tikrinama koreliacija (Mantel testas)…")
    rho, p_value = mantel(gen, lexd, perms)
    iu = np.triu_indices(n, 1)
    by_distance = []
    for dist in sorted({int(x) for x in gen[iu] if np.isfinite(x)}):
        vals = np.array([sim[i, j] for i, j in zip(*iu) if gen[i, j] == dist and np.isfinite(lexd[i, j])])
        if len(vals):
            q1, med, q3 = np.percentile(vals, [25, 50, 75])
            by_distance.append({"distance": dist, "pairs": int(len(vals)), "median": round(float(med), 4), "q1": round(float(q1), 4),
                                "q3": round(float(q3), 4), "min": round(float(vals.min()), 4), "max": round(float(vals.max()), 4)})
    expected = {b["distance"]: b["median"] for b in by_distance}
    residuals = []
    for i, j in zip(*iu):
        if np.isfinite(gen[i, j]) and np.isfinite(lexd[i, j]) and int(gen[i, j]) in expected:
            residuals.append((float(sim[i, j] - expected[int(gen[i, j])]), int(i), int(j)))
    residuals.sort()
    # contact candidates: branches differ yet the words agree; surprises the other way: close relatives that disagree
    same_branch = lambda i, j: langs[i]["path"][:branch_depth + 1] == langs[j]["path"][:branch_depth + 1]
    pair = lambda r: {"a": r[1], "b": r[2], "similarity": round(float(sim[r[1], r[2]]), 3), "expected": expected[int(gen[r[1], r[2]])],
                      "residual": round(r[0], 3), "distance": int(gen[r[1], r[2]]), "meanings": int(comparable[r[1], r[2]])}
    closer = [pair(r) for r in reversed(residuals) if r[0] > 0 and not same_branch(r[1], r[2])][:12]
    farther = [pair(r) for r in residuals if r[0] < 0 and same_branch(r[1], r[2])][:12]

    # -- 4. graphs: spectra and spectral clusters ----------------------------------------------------------------
    progress("Spektrinė analizė…")
    lex = affinity_clusters(w, k_wanted)
    labels, k = lex["labels"], lex["k"]
    gw = np.where(np.isfinite(gen), np.exp(-np.nan_to_num(gen, nan=1e9) / tau), 0.0)
    np.fill_diagonal(gw, 0)
    gvals, gvecs = laplacian_spectrum(gw)
    gen_labels = labels_for(gvecs, k)
    lex_xy, gen_xy = signed_embedding(lex["vectors"]), signed_embedding(gvecs)
    # the same distances laid out by multidimensional scaling (the spectral maps of a tree graph tend to
    # collapse onto a few languages; MDS keeps the distances readable)
    lex_mds = classical_mds(np.nan_to_num(lexd, nan=1.0))
    gen_mds = classical_mds(np.nan_to_num(gen, nan=np.nanmax(gen) + 1))

    # Glottolog clades at every depth below the common ancestor, and how well the lexical groups match each
    ancestor = langs[0]["path_names"][depth0] if len({l["path"][depth0] for l in langs}) == 1 else None
    clade = lambda l, lvl: l["path"][min(lvl, len(l["path"]) - 1)]
    clade_name = lambda l, lvl: l["path_names"][min(lvl, len(l["path_names"]) - 1)]
    levels = []
    max_depth = max(len(l["path"]) for l in langs) - 1
    for lvl in range(depth0 + 1, min(max_depth, depth0 + 8) + 1):
        tags = [clade(l, lvl) for l in langs]
        levels.append({"level": lvl - depth0, "clades": len(set(tags)), "ari_lexical": round(adjusted_rand(list(labels), tags) or 0, 3),
                       "ari_tree_spectrum": round(adjusted_rand(list(gen_labels), tags) or 0, 3),
                       "examples": [c for c, _ in Counter(clade_name(l, lvl) for l in langs).most_common(4)]})
    best_level = max(levels, key=lambda x: x["ari_lexical"]) if levels else None
    top = branch_depth
    for l in langs:
        l["branch"] = clade_name(l, top)
        l["subbranch"] = clade_name(l, top + 1)
    branch_sizes = Counter(l["branch"] for l in langs)
    branches = [b for b, _ in branch_sizes.most_common()]

    # -- 5. lexical tree against Glottolog branches ---------------------------------------------------------------
    progress("Leksinis medis…")
    tree = upgma(np.nan_to_num(lexd, nan=1.0))
    leaves_of = {i: [i] for i in range(n)}
    for t, (a, b, h, s) in enumerate(tree):
        leaves_of[n + t] = leaves_of[int(a)] + leaves_of[int(b)]
    leaf_order = leaves_of[n + len(tree) - 1] if tree else list(range(n))
    clades_of_tree = [set(v) for v in leaves_of.values()]
    branch_fit = []
    for b in branches:
        members = {i for i, l in enumerate(langs) if l["branch"] == b}
        smallest = min((c for c in clades_of_tree if members <= c), key=len)
        intruders = sorted(smallest - members, key=lambda i: langs[i]["name"])
        within = [sim[i, j] for i in members for j in members if i < j and np.isfinite(lexd[i, j])]
        between = [sim[i, j] for i in members for j in range(n) if j not in members and np.isfinite(lexd[i, j])]
        branch_fit.append({"branch": b, "languages": len(members), "monophyletic": not intruders, "intruders": intruders,
                           "within": round(float(np.mean(within)), 3) if within else None,
                           "between": round(float(np.mean(between)), 3) if between else None})

    # -- 6. each language: does its lexical neighbourhood follow the tree? ----------------------------------------
    for i, l in enumerate(langs):
        ok = [j for j in range(n) if j != i and np.isfinite(gen[i, j]) and np.isfinite(lexd[i, j])]
        l["fit"] = _gamma(gen[i, ok], lexd[i, ok])
        lex_nb = max(ok, key=lambda j: sim[i, j]) if ok else None
        gmin = min((gen[i, j] for j in ok), default=None)
        gen_nb = sorted((j for j in ok if gen[i, j] == gmin), key=lambda j: -sim[i, j]) if gmin is not None else []
        l.update({"cluster": int(labels[i]), "tree_cluster": int(gen_labels[i]),
                  "lx": round(float(lex_xy[i, 0]), 5), "ly": round(float(lex_xy[i, 1]), 5),
                  "gx": round(float(gen_xy[i, 0]), 5), "gy": round(float(gen_xy[i, 1]), 5),
                  "mx": round(float(lex_mds[i, 0]), 5), "my": round(float(lex_mds[i, 1]), 5),
                  "hx": round(float(gen_mds[i, 0]), 5), "hy": round(float(gen_mds[i, 1]), 5),
                  "lex_neighbor": lex_nb, "lex_neighbor_sim": round(float(sim[i, lex_nb]), 3) if lex_nb is not None else None,
                  "lex_neighbor_distance": int(gen[i, lex_nb]) if lex_nb is not None and np.isfinite(gen[i, lex_nb]) else None,
                  "tree_neighbors": gen_nb[:3], "tree_distance": int(gmin) if gmin is not None else None,
                  "mean_meanings": round(float(np.mean([comparable[i, j] for j in ok])), 1) if ok else 0})
        del l["path"]
    fits = sorted((l for l in langs if l["fit"] is not None), key=lambda l: l["fit"])

    clusters = []
    for c in range(k):
        ids = [i for i in range(n) if labels[i] == c]
        if not ids:
            continue
        br = Counter(langs[i]["branch"] for i in ids)
        top_b, top_n = br.most_common(1)[0]
        inner = [sim[i, j] for i in ids for j in ids if i < j and np.isfinite(lexd[i, j])]
        clusters.append({"id": c, "size": len(ids), "members": sorted(ids, key=lambda i: langs[i]["name"]),
                         "branches": br.most_common(), "top_branch": top_b, "top_share": top_n / len(ids),
                         "within": round(float(np.mean(inner)), 3) if inner else None})

    order_tree = sorted(range(n), key=lambda i: langs[i]["path_names"])
    result = {
        "study": STUDY["id"], "title": STUDY["title"],
        "input": {"scope": scope, "concepts": concepts, "meaning_filter": len(meaning_ids) if meaning_ids else None},
        "params": {"measure": measure, "min_overlap": min_overlap, "k": k_wanted, "tau": tau, "permutations": perms},
        "branch_level": top - depth0,
        "ancestor": ancestor,
        "summary": {"languages": n, "excluded": len(excluded), "pairs": n * (n - 1) // 2,
                    "pairs_compared": int(np.sum(np.isfinite(lexd[iu]) & np.isfinite(gen[iu]))),
                    "meanings": len(glosses), "rho": rho, "p_value": p_value, "rho_other": rho_other, "clusters": k, "k_auto": lex["k_auto"],
                    "best_level": best_level, "ari_trees": round(adjusted_rand(list(labels), list(gen_labels)) or 0, 3),
                    "monophyletic": sum(1 for b in branch_fit if b["monophyletic"]), "branches": len(branch_fit)},
        "languages": langs, "excluded": excluded, "branches": branches, "branch_fit": branch_fit, "clusters": clusters,
        "levels": levels, "by_distance": by_distance, "closer": closer, "farther": farther,
        "misfits": [langs.index(l) for l in fits[:10]],
        "spectrum": {"lexical": lex["eigenvalues"], "tree": [float(v) for v in gvals[:16]]},
        "tree": [[int(a), int(b), round(float(h), 4), int(s)] for a, b, h, s in tree], "leaf_order": leaf_order,
        "matrix": {"order": order_tree, "s": [[None if not np.isfinite(sim[i, j]) or comparable[i, j] < min_overlap and i != j
                                                else round(float(sim[i, j]), 3) for j in order_tree] for i in order_tree]},
    }
    result["findings"] = findings(result)
    return result


def _gamma(tree: np.ndarray, lexical: np.ndarray) -> float | None:
    """Goodman–Kruskal γ: of the pairs of other languages the tree puts in an order (ties skipped), the share the
    vocabulary orders the same way minus the share it orders the other way. A language of a lone branch (all other
    languages equally far in the tree) is judged only by the few pairs the tree does order."""
    if len(tree) < 3:
        return None
    a = np.sign(tree[:, None] - tree[None, :])
    b = np.sign(lexical[:, None] - lexical[None, :])
    ordered = int((a != 0).sum()) // 2
    if ordered < MIN_ORDERED:
        return None
    prod = a * b
    conc, disc = int((prod > 0).sum()), int((prod < 0).sum())
    return round((conc - disc) / (conc + disc), 3) if conc + disc else None


def _largest_component(w: np.ndarray) -> set[int]:
    n, seen, best = len(w), set(), set()
    for s in range(n):
        if s in seen:
            continue
        comp, stack = {s}, [s]
        while stack:
            v = stack.pop()
            for u in np.flatnonzero(w[v] > 0):
                if int(u) not in comp:
                    comp.add(int(u))
                    stack.append(int(u))
        seen |= comp
        if len(comp) > len(best):
            best = comp
    return best


def _mantel_text(p: float, perms: int) -> str:
    hits = max(0, round(p * (perms + 1)) - 1)
    times = "kartą" if hits % 10 == 1 and hits % 100 != 11 else "kartus" if 2 <= hits % 10 <= 9 and not 12 <= hits % 100 <= 19 else "kartų"
    seen = f"nepasitaikė nė karto per {perms} atsitiktinių sumaišymų (p ≤ {_num(p, 3)})" if hits == 0 else \
        f"pasitaikė {hits} {times} iš {perms} atsitiktinių sumaišymų (p = {_num(p, 3)})"
    return (f"Mantel testas: sumaišius kalbas atsitiktinai, tokia ar stipresnė koreliacija {seen}, todėl ryšys "
            f"{'ne atsitiktinis' if p < 0.05 else 'gali būti atsitiktinis'}. ")


def findings(r: dict[str, Any]) -> list[dict[str, Any]]:
    s, L = r["summary"], r["languages"]
    name = lambda i: L[i]["name"]
    out = []
    reasons = Counter(e["reason"] for e in r["excluded"])
    out.append({"id": "coverage", "title": f"Palygintos {_langs(s['languages'])} ir {s['pairs_compared']} jų porų",
                "text": f"Naudotos {s['meanings']} kognatais koduotos reikšmės"
                        + (f" (apribota krepšio sąvokomis)" if r["input"]["meaning_filter"] else "") + ". "
                        + f"Leksinis artumas – kokia dalis abiejose kalbose koduotų reikšmių išreikšta kognatais; poros, turinčios mažiau nei "
                          f"{r['params']['min_overlap']} bendrų reikšmių, nevertinamos. "
                        + (f"Neįtraukta {_langs(s['excluded'])} ({', '.join(f'{k}: {v}' for k, v in reasons.items())})." if s["excluded"] else "Neįtrauktų kalbų nėra.")})
    rho, p = s["rho"], s["p_value"]
    if rho is not None:
        out.append({"id": "rho", "title": f"Medis ir žodynas sutampa: ρ = {_num(rho)} ({_rho_words(rho)} koreliacija)",
                    "text": "Spearman ρ lygina kalbų porų atstumą Glottolog medyje su leksiniu atstumu (1 − artumas): 1 – tvarka visiškai ta pati, "
                            "0 – jokio ryšio. "
                            + (_mantel_text(p, r["params"]["permutations"]) if p is not None else "")
                            + "Tai tikrina, ar kognatų kodavimas ir Glottolog klasifikacija pasakoja tą pačią istoriją, bet neįrodo nė vienos jų."})
    if s.get("rho_other") is not None and rho is not None:
        anc = r["params"]["measure"] == "ancestor"
        r_anc, r_edge = (rho, s["rho_other"]) if anc else (s["rho_other"], rho)
        out.append({"id": "measure", "title": f"Genealoginio atstumo matas keičia vaizdą: protėvio gylis ρ {_num(r_anc)}, briaunos ρ {_num(r_edge)}",
                    "text": "Pirmajame bandyme atstumas buvo briaunų skaičius Glottolog medyje. Tačiau šakos turi labai skirtingą tarpinių mazgų skaičių: "
                            "indoarijų kalbos nuo šaknies nutolusios per 10 ir daugiau mazgų, albanų ar tocharų – per kelis. Tada tolimos, bet "
                            "„sekliose“ šakose esančios kalbos atrodo artimos. Bendro protėvio gylis (kiek lygių žemiau šaknies yra paskutinis bendras "
                            "protėvis) šios klaidos nedaro"
                            + (", todėl ir su žodynu sutampa geriau." if r_anc > r_edge else ".")
                            + f" Šiame tyrime naudojamas: {'bendro protėvio gylis' if anc else 'briaunų skaičius'}."})
    bd = r["by_distance"]
    if len(bd) >= 2:
        a, b = bd[0], bd[-1]
        out.append({"id": "decay", "title": "Kuo toliau medyje, tuo mažiau bendrų kognatų",
                    "text": f"Artimiausios medyje poros (atstumas {a['distance']}) vidutiniškai (mediana) dalijasi {_pct(a['median'])} reikšmių kognatais, "
                            f"tolimiausios (atstumas {b['distance']}) – {_pct(b['median'])}. Plati juosta ties vienu atstumu rodo, kad tas pats medžio "
                            "atstumas nereiškia to paties laiko: vienos šakos išsiskyrė seniau, kitos vėliau, o medis to nematuoja."})
    bl = s["best_level"]
    out.append({"id": "clusters", "title": f"Žodynas skyla į {s['clusters']} grupes"
                + (f", kurios labiausiai atitinka {bl['level']}-ąjį medžio lygį (ARI {_num(bl['ari_lexical'])})" if bl else ""),
                "text": ("Leksinio grafo Laplaso savųjų reikšmių tarpas siūlo "
                         + (f"{s['k_auto']} grupes" if s["clusters"] == s["k_auto"] else f"{s['k_auto']} grupes (jūs nurodėte {s['clusters']})") + ". "
                         + (f"Tame lygyje yra {bl['clades']} Glottolog šakų, pvz. {', '.join(bl['examples'][:4])}; leksinės grupės su jomis {_ari_words(bl['ari_lexical'])}. " if bl else "")
                         + f"Tiek pat grupių padalijus patį medžio grafą, abu padalijimai {_ari_words(s['ari_trees'])} (ARI {_num(s['ari_trees'])}).")})
    for cl in r["clusters"]:
        mixed = [f"{b} ({c})" for b, c in cl["branches"][1:4]]
        out.append({"id": f"cluster-{cl['id']}", "cluster": cl["id"],
                    "title": f"{cl['id'] + 1} grupė: {cl['top_branch']} ({_langs(cl['size'])})",
                    "text": f"{_pct(cl['top_share'])} šios grupės kalbų yra iš šakos {cl['top_branch']}"
                            + (f"; kartu – {', '.join(mixed)}" if mixed else "") + f". Viduje kalbos vidutiniškai dalijasi {_pct(cl['within'])} reikšmių. "
                            + f"Kalbos: {', '.join(name(i) for i in cl['members'][:8])}{'…' if cl['size'] > 8 else ''}."})
    multi = [b for b in r["branch_fit"] if b["languages"] > 1]
    mono = [b for b in multi if b["monophyletic"]]
    broken = [b for b in multi if not b["monophyletic"]]
    single = len(r["branch_fit"]) - len(multi)
    out.append({"id": "tree", "title": f"Leksiniame medyje vientisos {len(mono)} iš {len(multi)} šakų"
                + (f" (dar {single} – po vieną kalbą)" if single else ""),
                "text": "Iš leksinių atstumų sudarytas medis (vidutinio ryšio grupavimas, UPGMA). Šaka vientisa, jei visos jos kalbos jame "
                        "susijungia anksčiau nei su bet kuria kita. "
                        + (f"Vientisos: {', '.join(b['branch'] for b in mono)}. " if mono else "")
                        + ("; ".join(f"{b['branch']} – įsiterpia {', '.join(name(i) for i in b['intruders'][:4])}{'…' if len(b['intruders']) > 4 else ''}"
                                     for b in broken[:5]) + ". " if broken else "")
                        + "Įsiterpimai dažniausiai rodo kontaktą (skolinius), negausius duomenis arba tai, kad šaka dalijasi senu paveldu su kaimyne."})
    if r["tree"]:
        a, b = r["tree"][-1][0], r["tree"][-1][1]
        n = len(L)
        leaves = {i: [i] for i in range(n)}
        for t, (x, y, _h, _s) in enumerate(r["tree"]):
            leaves[n + t] = leaves[x] + leaves[y]
        small, big = sorted([leaves[a], leaves[b]], key=len)
        comp = Counter(L[i]["branch"] for i in small)
        out.append({"id": "rootsplit", "title": f"Pirmiausia leksiniame medyje atsiskiria: {', '.join(comp)}",
                    "text": f"Didžiausias leksinio medžio skilimas atskiria {_langs(len(small))} ({', '.join(f'{b} {c}' for b, c in comp.items())}) "
                            f"nuo likusių {len(big)}: jos turi mažiausiai kognatų su visomis kitomis. Tai būdinga seniai atsiskyrusioms šakoms, "
                            "smarkiai atnaujintam žodynui arba menkai paliudytoms kalboms (mažai koduotų reikšmių)."
                            + (" Kelios šakos čia susijungia ne būtinai dėl bendros kilmės: UPGMA jas jungia, nes jos visos panašiai toli nuo kitų."
                               if len(comp) > 1 else "")})
    if r["misfits"]:
        out.append({"id": "misfits", "title": "Kalbos, kurių žodynas mažiausiai seka medį",
                    "text": "Kiekvienai kalbai tikrinta: kai medis sako, kad kalba A jai artimesnė už B, ar ir žodynas taip sako? "
                            "γ = 1 – visada, 0 – kaip atsitiktinai, < 0 – dažniau atvirkščiai. "
                            "Mažiausiai sutampa: " + ", ".join(f"{name(i)} (γ {_num(L[i]['fit'])})" for i in r["misfits"][:5])
                            + ". Priežastys gali būti skolinių gausa, mažai koduotų reikšmių, archajiškumas (seniai paliudyta kalba) ar ginčytina vieta medyje."
                            + (f" Nevertinta {_langs(unjudged)}: medis beveik neskiria, kurios kitos kalbos joms artimesnės (vieniša šaka su menkai paliudyta seserimi)."
                               if (unjudged := sum(1 for l in L if l["fit"] is None)) else "")})
    if r["closer"]:
        out.append({"id": "closer", "title": "Skirtingų šakų kalbos, leksiškai artimesnės, nei leidžia medis",
                    "text": "Lyginama su tipišku (medianos) artumu tame pačiame medžio atstume; imamos tik skirtingų šakų poros: "
                            + "; ".join(f"{name(x['a'])} – {name(x['b'])} {_pct(x['similarity'])} vietoj ~{_pct(x['expected'])}" for x in r["closer"][:5])
                            + ". Tai kandidatai tyrinėti kontaktus ir skolinius; genealogija čia nieko nepaaiškina."})
    if r["farther"]:
        out.append({"id": "farther", "title": "Tos pačios šakos kalbos, leksiškai tolimesnės, nei leidžia medis",
                    "text": "; ".join(f"{name(x['a'])} – {name(x['b'])} {_pct(x['similarity'])} vietoj ~{_pct(x['expected'])}" for x in r["farther"][:5])
                            + ". Taip būna, kai viena kalba smarkiai atnaujino žodyną arba viena iš jų paliudyta menkai (maža bendrų reikšmių aibė)."})
    out.append({"id": "method", "title": "Kaip tai apskaičiuota",
                "text": "Genealoginis atstumas – bendro protėvio gylis (giliausias bendras protėvis – 0) arba briaunų skaičius Glottolog medyje tarp "
                        "kalbų atitikmenų; 0, jei du įrašai rodo į tą patį Glottolog mazgą. "
                        "Leksinis artumas S = C/M: M – abiejose kalbose koduotos Concepticon reikšmės, C – kiek jų turi bendrą kognatų grupę; "
                        "kiekviena reikšmė skaičiuojama vieną kartą. Leksinio grafo svoriai – S (tik poros su M ≥ riba), medžio grafo – exp(−atstumas/τ). "
                        "Abiejų grafų normalizuotos Laplaso matricos savieji vektoriai duoda žemėlapius ir grupes (k-vidurkiai). "
                        "Mantel testas maišo vieno matricos kalbas ir žiūri, kaip dažnai atsitiktinė koreliacija ne silpnesnė už tikrąją."})
    return out
