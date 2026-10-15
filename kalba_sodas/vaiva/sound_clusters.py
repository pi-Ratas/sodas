"""Study „Formų garsinio panašumo spektrinė klasterizacija“.

Concept (and the concepts it CORRESPONDS_TO) → Sense → Lexeme → Form; or the forms of basket senses, lexemes,
cognate sets and the basket forms themselves. Each form gets analysis segments (see ``segments``), each segment a
CLTS sound (see ``phonology``); forms are compared with a feature-weighted edit distance and clustered spectrally.
IE-CoR cognacy and the Glottolog branch are used only afterwards, to check and read the clusters.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .phonology import SoundTable, edit_distance
from .segments import SOURCE_LABELS, analysis_segments, profile_for
from .spectral import MAX_K, adjusted_rand, labels_for, silhouette, spectral_clusters

STUDY = {
    "id": "garsiniai-klasteriai",
    "title": "Formų garsinio panašumo spektrinė klasterizacija",
    "summary": "Krepšio sąvokos (ar reikšmės, leksemos, kognatų grupės, formos) formos sugrupuojamos pagal tai, kaip "
               "panašiai jos skamba. Garsai lyginami pagal CLTS fonetinius požymius, grupės randamos spektriniu metodu, "
               "o tada palyginamos su IE-CoR kognatais ir Glottolog kalbų šakomis.",
    "accepts": ["Concept", "Sense", "Lexeme", "Form", "CognateSet"],
    "datasets": ["clts"],   # read in any case (bibliography: kalba_sodas.sekimas)
    "params": [
        {"name": "k", "label": "Klasterių skaičius", "type": "number", "min": 2, "max": 30, "default": None,
         "hint": "tuščia – parenka pats pagal savųjų reikšmių tarpą",
         "help": "Į kiek grupių skirstyti formas. Tuščia – programa parenka pati: ten, kur didžiausias tarpas tarp gretimų Laplaso matricos savųjų reikšmių (renkamasi iš 2–12). Daugiau grupių – smulkesni, bet mažiau patikimi garsiniai skirtumai."},
        {"name": "include_reconstructed", "label": "Įtraukti rekonstruotas (*) formas", "type": "bool", "default": False,
         "help": "Ar tirti ir rekonstruotas prokalbių formas (pažymėtas *, pvz. *méh₁n̥s). Jos užrašomos kitaip nei paliudytos formos ir neturi vienos kalbos vietos, todėl paprastai paliekamos nuošalyje."},
        {"name": "max_forms", "label": "Daugiausia formų", "type": "number", "min": 10, "max": 1500, "default": 600,
         "help": "Kiek daugiausia formų paimti iš krepšio mazgų; kitos praleidžiamos (apie tai pranešama). Lyginamos visos formų poros, tad darbo daugėja kvadratu: 600 formų – apie 180 000 porų."},
    ],
}

FORMS_OF = {
    "Concept": "MATCH (c:Concept {key: $key}) OPTIONAL MATCH (c)-[:CORRESPONDS_TO]-(c2:Concept) "
               "WITH c, collect(DISTINCT c2) AS others UNWIND [c] + others AS cc "
               "MATCH (cc)-[:DENOTES]-(:Sense)<-[:HAS_SENSE]-(:Lexeme)-[:HAS_FORM]->(f:Form) RETURN DISTINCT f.key AS key",
    "Sense": "MATCH (:Sense {key: $key})<-[:HAS_SENSE]-(:Lexeme)-[:HAS_FORM]->(f:Form) RETURN DISTINCT f.key AS key",
    "Lexeme": "MATCH (:Lexeme {key: $key})-[:HAS_FORM]->(f:Form) RETURN DISTINCT f.key AS key",
    "Form": "MATCH (f:Form {key: $key}) RETURN f.key AS key",
    "CognateSet": "MATCH (f:Form)-[:COGNATE_IN]->(:CognateSet {key: $key}) RETURN DISTINCT f.key AS key",
}

FORM_DETAILS = (
    "UNWIND $keys AS k MATCH (f:Form {key: k}) "
    "OPTIONAL MATCH (l:Lexeme)-[:HAS_FORM]->(f) OPTIONAL MATCH (l)-[:USED_IN]->(lang:Languoid) "
    "OPTIONAL MATCH (rec:SourceRecord {key: f.source_record_key}) "
    "OPTIONAL MATCH (f)-[:COGNATE_IN]->(cs:CognateSet) "
    "RETURN f.key AS key, f.display_name AS name, f.dataset AS dataset, f.segments AS segments, "
    "coalesce(f.written, f.value, f.display_name) AS written, rec.raw_json AS raw, "
    "head(collect(DISTINCT lang.key)) AS lang_key, head(collect(DISTINCT lang.display_name)) AS lang, "
    "collect(DISTINCT {key: cs.key, name: cs.display_name}) AS cognates"
)

LINEAGE = (
    "UNWIND $keys AS k MATCH (l:Languoid {key: k}) "
    "OPTIONAL MATCH (l)-[:IDENTIFIED_BY]->(e:ExternalIdentifier {scheme: 'glottolog:glottocode'}) "
    "WITH l, CASE WHEN l.key STARTS WITH 'languoid:' THEN l.key ELSE 'languoid:' + e.value END AS gk "
    "OPTIONAL MATCH (g:Languoid {key: gk}) "
    "OPTIONAL MATCH p = (top:Languoid)-[:PARENT_OF*0..]->(g) WHERE NOT ()-[:PARENT_OF]->(top) "
    "RETURN l.key AS key, [n IN nodes(p) | n.display_name] AS names"
)

# validated categorical palette (light steps; the page swaps in the dark ones); past 8 groups: neutral, the number identifies
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER_COLOR = "#9a9893"


def _num(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)} %" if whole else "–"


def _forms(p: int) -> str:
    """Lithuanian plural of „forma“."""
    if p % 10 == 1 and p % 100 != 11:
        return f"{p} forma"
    if 2 <= p % 10 <= 9 and not 12 <= p % 100 <= 19:
        return f"{p} formos"
    return f"{p} formų"


def _closeness(x: float) -> str:
    if x < 0.15:
        return "labai panašios"
    if x < 0.3:
        return "gana panašios"
    if x < 0.45:
        return "vidutiniškai panašios"
    return "skamba gana skirtingai"


def _ari_words(x: float | None) -> str:
    if x is None:
        return "nepakanka duomenų"
    if x >= 0.8:
        return "beveik sutampa"
    if x >= 0.5:
        return "gerokai sutampa"
    if x >= 0.2:
        return "sutampa iš dalies"
    return "beveik nesutampa"


def collect_forms(read: Callable[..., list[Any]], nodes: list[dict[str, Any]], max_forms: int
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int]:
    """Form keys of the basket nodes: (used nodes with their form counts, ignored nodes, keys, how many cut off)."""
    used, ignored, keys = [], [], []
    for n in nodes:
        q = FORMS_OF.get(n.get("label"))
        if q is None:
            ignored.append(n)
            continue
        got = [r["key"] for r in read(q, key=n["key"])]
        used.append({**n, "forms": len(got)})
        keys.extend(k for k in got if k not in keys)
    truncated = max(0, len(keys) - max_forms)
    return used, ignored, keys[:max_forms], truncated


def segment_forms(read: Callable[..., list[Any]], keys: list[str], dataset_paths: dict[str, Path], include_rec: bool
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The forms with their analysis segments (``variants``), and those left out with the reason."""
    rows = {r["key"]: r for r in read(FORM_DETAILS, keys=keys)}
    included, excluded = [], []
    for key in keys:
        r = rows.get(key)
        if r is None:
            continue
        raw = json.loads(r["raw"]) if r["raw"] else {}
        seg = analysis_segments(r["segments"], raw, r["written"] or raw.get("Form") or raw.get("Value"),
                                profile_for(dataset_paths.get(r["dataset"])), include_rec)
        base = {"key": key, "name": r["name"], "dataset": r["dataset"], "language": r["lang"], "language_key": r["lang_key"],
                "written": r["written"], "cognates": [c for c in r["cognates"] if c.get("key")]}
        if seg.reason:
            excluded.append({**base, "reason": seg.reason, "detail": seg.detail})
        else:
            included.append({**base, "variants": seg.variants, "source": seg.source, "note": seg.detail,
                             "reconstructed": seg.reconstructed})
    return included, excluded


def sound_distances(read: Callable[..., list[Any]], variants: list[list[list[str]]], progress: Callable[[str], None] = lambda m: None
                    ) -> tuple[np.ndarray, SoundTable, list[str]]:
    """Feature-weighted edit distances of forms given as their variants (lists of segments); the smallest over variants."""
    progress("Garsai susiejami su CLTS…")
    table = SoundTable(read)
    symbols = sorted({s for vs in variants for v in vs for s in v})
    table.resolve(set(symbols))
    index = {s: i for i, s in enumerate(symbols)}
    sub = [[table.distance(a, b) for b in symbols] for a in symbols]
    n = len(variants)
    progress(f"Skaičiuojami {n * (n - 1) // 2} formų porų atstumai…")
    seqs = [[[index[s] for s in v] for v in vs] for vs in variants]
    d = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d[i, j] = d[j, i] = min(edit_distance(a, b, sub) for a in seqs[i] for b in seqs[j])
    return d, table, symbols


def lineages(read: Callable[..., list[Any]], lang_keys: list[str]) -> dict[str, list[str]]:
    """Glottolog lineage (names from the top) of every language key; the longest when there are several."""
    out: dict[str, list[str]] = {}
    for r in read(LINEAGE, keys=lang_keys) if lang_keys else []:
        if r["names"] and len(r["names"]) > len(out.get(r["key"], [])):
            out[r["key"]] = r["names"]
    return out


def run(read: Callable[..., list[Any]], nodes: list[dict[str, Any]], params: dict[str, Any],
        dataset_paths: dict[str, Path], progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    include_rec = bool(params.get("include_reconstructed"))
    max_forms = int(params.get("max_forms") or 600)
    k_wanted = int(params["k"]) if params.get("k") not in (None, "", 0) else None

    # -- 1. forms ----------------------------------------------------------------------------------------------
    progress("Renkamos formos…")
    used, ignored, keys, truncated = collect_forms(read, nodes, max_forms)
    if not keys:
        raise ValueError("Krepšyje nėra formų: įdėkite sąvoką, reikšmę, leksemą, kognatų grupę ar formas.")

    # -- 2. analysis segments -------------------------------------------------------------------------------
    progress("Ruošiami analizės segmentai…")
    included, excluded = segment_forms(read, keys, dataset_paths, include_rec)
    if len(included) < 3:
        raise ValueError(f"Tirti tinka tik {len(included)} formos(-ų) iš {len(keys)}: per mažai klasterizavimui.")

    # -- 3, 4. CLTS sounds, distances ------------------------------------------------------------------------
    d, table, symbols = sound_distances(read, [f["variants"] for f in included], progress)
    n = len(included)

    # -- 5. spectral clustering ------------------------------------------------------------------------------
    progress("Spektrinė analizė…")
    sc = spectral_clusters(d, k_wanted)
    labels, k = sc["labels"], sc["k"]
    sil = silhouette(d, labels)
    layout = sc["layout"]
    span = float(np.abs(layout).max()) or 1.0

    # -- 6. genealogy ----------------------------------------------------------------------------------------
    lineage = lineages(read, sorted({f["language_key"] for f in included + excluded if f.get("language_key")}))
    paths = [lineage.get(f["language_key"]) for f in included if lineage.get(f["language_key"])]
    depth = 0
    while paths and all(len(p) > depth for p in paths) and len({p[depth] for p in paths}) == 1:
        depth += 1
    family = paths[0][depth - 1] if paths and depth else None
    for f in included + excluded:
        p = lineage.get(f.get("language_key")) or []
        f["branch"] = p[depth] if len(p) > depth else (p[-1] if p else None)
        f["lineage"] = p

    # -- 7. forms, clusters ----------------------------------------------------------------------------------
    for i, f in enumerate(included):
        f.update({"cluster": int(labels[i]), "x": round(float(layout[i, 0]) / span, 4), "y": round(float(layout[i, 1]) / span, 4),
                  "sx": round(float(sc["embedding"][i, 0]), 5) if len(sc["embedding"]) else 0,
                  "sy": round(float(sc["embedding"][i, 1]) if sc["embedding"].shape[1] > 1 else 0, 5),
                  "silhouette": round(float(sil[i]), 3), "segments": " ".join(f["variants"][0]),
                  "variants_text": [" ".join(v) for v in f["variants"]],
                  "cognate": f["cognates"][0]["name"] if f["cognates"] else None,
                  "cognate_key": f["cognates"][0]["key"] if f["cognates"] else None})
        order = np.argsort(d[i])
        f["neighbors"] = [{"i": int(j), "d": round(float(d[i, j]), 3)} for j in order if j != i][:3]
        del f["variants"]

    clusters = []
    for c in range(k):
        idx = [i for i in range(n) if labels[i] == c]
        if not idx:
            continue
        sub_d = d[np.ix_(idx, idx)]
        medoid = idx[int(sub_d.sum(1).argmin())]
        intra = float(sub_d[np.triu_indices(len(idx), 1)].mean()) if len(idx) > 1 else 0.0
        outside = [i for i in range(n) if labels[i] != c]
        inter = float(d[np.ix_(idx, outside)].mean()) if outside else 0.0
        cog = Counter(included[i]["cognate"] or "—" for i in idx)
        br = Counter(included[i]["branch"] or "—" for i in idx)
        top_cog, top_cog_n = cog.most_common(1)[0]
        top_br, top_br_n = br.most_common(1)[0]
        members = sorted(idx, key=lambda i: d[medoid, i])
        clusters.append({
            "id": c, "color": COLORS[c] if c < len(COLORS) else OTHER_COLOR, "size": len(idx), "medoid": medoid, "medoid_name": included[medoid]["name"],
            "intra": round(intra, 3), "inter": round(inter, 3), "silhouette": round(float(sil[idx].mean()), 3),
            "cognates": cog.most_common(6), "branches": br.most_common(6),
            "top_cognate": top_cog, "top_cognate_share": top_cog_n / len(idx), "top_branch": top_br, "top_branch_share": top_br_n / len(idx),
            "members": members, "examples": [included[i]["name"] for i in members[:6]],
        })

    # -- 8. comparison with cognacy and genealogy ------------------------------------------------------------
    with_cog = [i for i in range(n) if included[i]["cognate_key"]]
    ari_cog = adjusted_rand([int(labels[i]) for i in with_cog], [included[i]["cognate_key"] for i in with_cog]) if len(with_cog) > 2 else None
    with_br = [i for i in range(n) if included[i]["branch"]]
    ari_br = adjusted_rand([int(labels[i]) for i in with_br], [included[i]["branch"] for i in with_br]) if len(with_br) > 2 else None
    purity = sum(round(cl["top_cognate_share"] * cl["size"]) for cl in clusters if cl["top_cognate"] != "—") / len(with_cog) if with_cog else None
    # how many sound groups the larger cognate sets fall into
    splits = []
    for cog, total in Counter(included[i]["cognate"] for i in with_cog).most_common():
        if total < 4:
            break
        parts = Counter(int(labels[i]) for i in with_cog if included[i]["cognate"] == cog)
        splits.append({"cognate": cog, "forms": total, "clusters": [[c, m] for c, m in parts.most_common()]})
    # "Kiek grupių?": the same eigenvectors cut into 2 … 12 groups
    scan = []
    for kk in range(2, min(MAX_K, n - 1) + 1):
        lab = labels if kk == k else labels_for(sc["vectors"], kk)
        scan.append({"k": kk, "gap": round(sc["gaps"][kk - 1], 4) if len(sc["gaps"]) >= kk else None,
                     "silhouette": round(float(silhouette(d, lab).mean()), 3),
                     "ari_cognate": round(adjusted_rand([int(lab[i]) for i in with_cog], [included[i]["cognate_key"] for i in with_cog]), 3)
                     if len(with_cog) > 2 else None})
    cog_names = [c for c, _ in Counter(included[i]["cognate"] for i in with_cog).most_common(12)]
    br_names = [b for b, _ in Counter(included[i]["branch"] for i in with_br).most_common(12)]
    contingency = {
        "cognates": {"columns": cog_names, "rows": [[sum(1 for i in cl["members"] if included[i]["cognate"] == c) for c in cog_names] for cl in clusters]},
        "branches": {"columns": br_names, "rows": [[sum(1 for i in cl["members"] if included[i]["branch"] == b) for b in br_names] for cl in clusters]},
    }

    # -- 9. sounds summary ------------------------------------------------------------------------------------
    usage = Counter(s for f in included for v in f["variants_text"] for s in v.split())
    sounds = [{**table.sounds[s].out(), "count": usage.get(s, 0)} for s in symbols]
    via = Counter(s["via"] for s in sounds)

    order = [i for cl in clusters for i in cl["members"]]
    result = {
        "study": STUDY["id"], "title": STUDY["title"],
        "input": {"used": used, "ignored": ignored, "truncated": truncated},
        "params": {"k": k_wanted, "include_reconstructed": include_rec, "max_forms": max_forms},
        "family": family,
        "summary": {"forms": len(keys), "included": n, "excluded": len(excluded), "clusters": k, "k_auto": sc["k_auto"],
                    "sources": dict(Counter(f["source"] for f in included)), "sounds": len(symbols), "sounds_via": dict(via),
                    "ari_cognate": ari_cog, "ari_branch": ari_br, "silhouette": round(float(sil.mean()), 3),
                    "purity": round(purity, 3) if purity is not None else None},
        "splits": splits, "scan": scan,
        "forms": included, "excluded": excluded, "clusters": clusters, "sounds": sounds,
        "spectrum": {"eigenvalues": sc["eigenvalues"], "gaps": sc["gaps"][:15]},
        "matrix": {"order": order, "d": [[round(float(d[i, j]), 3) for j in order] for i in order]} if n <= 350 else None,
        "contingency": contingency,
        "method": {"indel": 0.5, "knn": 7, "distance": "CLTS požymiais svertas redagavimo atstumas, padalytas iš ilgesnės formos ilgio"},
    }
    result["findings"] = findings(result, clusters, included)
    return result


def findings(r: dict[str, Any], clusters: list[dict[str, Any]], forms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = r["summary"]
    out = []
    src = s["sources"]
    parts = [f"{_forms(v)} – {SOURCE_LABELS[k]}" for k, v in src.items()]
    reasons = Counter(e["reason"] for e in r["excluded"])
    out.append({"id": "coverage", "title": f"Ištirta {s['included']} iš {s['forms']} formų ({_pct(s['included'], s['forms'])})",
                "text": "Segmentai imami iš pirminių duomenų, o ne spėjami: " + "; ".join(parts) + "."
                        + (f" Neįtraukta {_forms(s['excluded'])} ({', '.join(f'{k}: {v}' for k, v in reasons.items())}) – "
                           "jos parodytos lentelėje „Neįtrauktos formos“ su priežastimi." if s["excluded"] else " Neįtrauktų formų nėra.")
                        + (f" Dėl ribos neimta dar {r['input']['truncated']} formų." if r["input"]["truncated"] else "")})
    via = s["sounds_via"]
    out.append({"id": "sounds", "title": f"{s['sounds']} skirtingų garsų susieta su CLTS",
                "text": f"BIPA atpažino {via.get('bipa', 0)}, kitos CLTS sistemos vienareikšmiškai – {via.get('system', 0)}, "
                        f"apytiksliai (be kai kurių diakritikų) – {via.get('approx', 0)}, neatpažinta – {via.get('unknown', 0)}. "
                        "Atpažinti garsai lyginami pagal fonetinius požymius (m ir n skiriasi mažiau nei m ir a); "
                        "neatpažinti – tik kaip tas pats ar kitas simbolis."})
    ev = r["spectrum"]["eigenvalues"]
    k, ka = s["clusters"], s["k_auto"]
    gap_txt = f"didžiausias tarpas yra tarp {ka}-os ir {ka + 1}-os savosios reikšmės ({_num(ev[ka - 1], 3)} → {_num(ev[ka], 3)})" \
        if len(ev) > ka else "savųjų reikšmių per mažai"
    out.append({"id": "k", "title": f"Rasta {k} garsinių grupių",
                "text": (f"Spektrinė analizė pati pasiūlė {ka}: {gap_txt}. Kuo didesnis toks tarpas, tuo aiškiau duomenys "
                         "skyla į tiek grupių." if k == ka else
                         f"Grupių skaičių ({k}) nurodėte patys; pagal savųjų reikšmių tarpą būtų {ka} ({gap_txt}).")
                + f" Vidutinis siluetas {_num(s['silhouette'])} (nuo −1 iki 1; virš 0,5 – grupės ryškios, apie 0 – susiliejančios)."})
    for cl in clusters:
        cog = f"{_pct(round(cl['top_cognate_share'] * cl['size']), cl['size'])} jų priklauso kognatų grupei „{cl['top_cognate']}“" \
            if cl["top_cognate"] != "—" else "kognatų informacijos jos neturi"
        br = f"dažniausia šaka – {cl['top_branch']} ({_pct(round(cl['top_branch_share'] * cl['size']), cl['size'])})" \
            if cl["top_branch"] != "—" else "kalbų šaka nežinoma"
        out.append({"id": f"cluster-{cl['id']}", "cluster": cl["id"],
                    "title": f"{cl['id'] + 1} grupė · „{cl['medoid_name']}“ tipo ({_forms(cl['size'])})",
                    "text": f"Pavyzdžiai: {', '.join(cl['examples'])}. Grupės viduje formos {_closeness(cl['intra'])} "
                            f"(vidutinis atstumas {_num(cl['intra'])}, iki kitų grupių {_num(cl['inter'])}). {cog.capitalize()}; {br}."})
    border = sorted((f for f in forms if f["silhouette"] < 0), key=lambda f: f["silhouette"])
    if border:
        out.append({"id": "border", "title": f"{_forms(len(border))} tarp grupių",
                    "text": "Šios formos panašios ir į kitos grupės formas, todėl jų vieta neaiški: "
                            + ", ".join(f"{f['name']} ({f['language'] or '?'})" for f in border[:10])
                            + ("…" if len(border) > 10 else "") + ". Lentelėje jų siluetas neigiamas."})
    if s["ari_cognate"] is not None:
        out.append({"id": "cognacy", "title": f"Su IE-CoR kognatais grupės {_ari_words(s['ari_cognate'])} (ARI {_num(s['ari_cognate'])})",
                    "text": "Pakoreguotas Rand indeksas lygina dvi grupuotes: 1 – visiškai sutampa, 0 – ne daugiau nei atsitiktinai. "
                            "Garsinis panašumas nėra kilmės įrodymas: sutapimas rodo, kad kognatai dažnai tebeskamba panašiai, "
                            "o nesutapimai – kur garsai nutolo arba panašumas atsitiktinis."})
    if s.get("purity") is not None:
        cl_name = {cl["id"]: f"{cl['id'] + 1} („{cl['medoid_name']}“)" for cl in clusters}
        split = [x for x in r["splits"] if len(x["clusters"]) > 1 and x["clusters"][1][1] >= 2]
        pure = s["purity"]
        level = "grynos" if pure >= 0.8 else "gana grynos" if pure >= 0.6 else "mišrios"
        out.append({"id": "purity", "title": f"Grupės {level}: {_pct(round(pure * 100), 100)} formų yra savo grupės daugumos kognatų grupėje",
                    "text": "Grynumas rodo, ar į vieną garsinę grupę nepatenka skirtingos kilmės žodžiai. "
                            + (("Žemą ARI daugiausia lemia ne maišymas, o skaidymas: " if pure >= 0.6 else
                                "Grupėse maišosi skirtingos kilmės žodžiai, be to, kognatų grupės skaidosi: ")
                               + "; ".join(f"„{x['cognate']}“ ({_forms(x['forms'])}) pasiskirsto į grupes "
                                           + ", ".join(f"{cl_name.get(c, c + 1)} – {m}" for c, m in x["clusters"][:4])
                                           for x in split[:3])
                               + ". Vienos kilmės žodžiai kalbose nutolo garsiškai, todėl sudaro kelias garsines grupes."
                               if split else "Didesnės kognatų grupės nesiskaido į kelias garsines grupes.")})
    if s["ari_branch"] is not None:
        out.append({"id": "branches", "title": f"Su kalbų šakomis grupės {_ari_words(s['ari_branch'])} (ARI {_num(s['ari_branch'])})",
                    "text": (f"Šakos imamos iš Glottolog medžio žemiau „{r['family']}“. " if r.get("family") else "Šakos imamos iš Glottolog medžio. ")
                            + "Jei tas pats žodis paplitęs keliose šakose (skolinys ar bendras paveldas), garsinė grupė apima kelias šakas."})
    out.append({"id": "method", "title": "Kaip tai apskaičiuota",
                "text": "Kiekvienai formų porai skaičiuojamas redagavimo atstumas: garso pakeitimas kainuoja tiek, kokia dalis jų CLTS "
                        "požymių skiriasi (0–1), įterpimas ar praleidimas – 0,5; rezultatas dalijamas iš ilgesnės formos ilgio. "
                        "Formoms su keliais variantais imamas mažiausias atstumas. Iš atstumų sudaromas panašumo grafas, jo Laplaso "
                        "matricos savieji vektoriai padeda formas į erdvę, kur jos grupuojamos k-vidurkiais. Paveiksle formos "
                        "išdėstytos klasikiniu daugiamačiu skalavimu – kuo arčiau, tuo panašiau skamba."})
    return out
