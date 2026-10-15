"""Measures: how far apart or how alike every pair of units is."""
from __future__ import annotations

from collections import Counter

import numpy as np

from .. import sound_clusters, tree_fit
from ..segments import SOURCE_LABELS, analysis_segments, profile_for
from .core import ANY, SAME, Distances, Items, Param, Port, Similarities, attribute, part

MAX_SOUND_FORMS = 1500


@part("garsinis_atstumas", "Matai", datasets=("clts",), title="Garsinis atstumas (CLTS)",
      summary="Kiek skirtingai skamba dvi formos: redagavimo atstumas, kur garso pakeitimas kainuoja skirtingų CLTS požymių dalį.",
      inputs=[Port("formos", ("items",), label="Formos")],
      outputs=[Port("atstumai", ("dist",))],
      params=[Param("include_reconstructed", "Įtraukti rekonstruotas (*) formas", "bool", False,
                    help="Ar tirti ir rekonstruotas prokalbių formas (pažymėtas *). Jos užrašomos kitaip nei paliudytos formos, "
                         "todėl paprastai paliekamos nuošalyje.")],
      help="Analizės segmentai imami iš Form.segments, tada IE-CoR Phonemic_Segments, tada duomenyno etc/orthography.tsv; "
           "jei forma neturi nė vieno, ji neįtraukiama (tarimas neišradinėjamas). Kiekvienas segmentas susiejamas su CLTS "
           "garsu. Įterpimas ar praleidimas kainuoja 0,5, rezultatas dalijamas iš ilgesnės formos ilgio (0–1); formoms su "
           "keliais variantais imamas mažiausias atstumas.")
def garsinis_atstumas(ctx, inputs, params):
    items: Items = inputs["formos"]
    if items.kind != "forma":
        raise ValueError("Garsinis atstumas skaičiuojamas tik formoms.")
    keep, rows, variants, sources = [], [], [], Counter()
    for i, r in enumerate(items.rows):
        seg = analysis_segments(r.get("_segments"), r.get("_raw") or {}, r.get("_written") or (r.get("_raw") or {}).get("Form")
                                or (r.get("_raw") or {}).get("Value"), profile_for(ctx.dataset_paths.get(r.get("dataset"))),
                                params["include_reconstructed"])
        if seg.reason:
            ctx.drop(r, seg.reason, seg.detail)
            continue
        keep.append(i)
        variants.append(seg.variants)
        sources[seg.source] += 1
        rows.append({**r, "segments": " | ".join(" ".join(v) for v in seg.variants), "segment_source": SOURCE_LABELS[seg.source]})
    if len(keep) < 3:
        raise ValueError(f"Tirti tinka tik {len(keep)} formos(-ų) iš {len(items)}.")
    if len(keep) > MAX_SOUND_FORMS:
        raise ValueError(f"Per daug formų ({len(keep)}; daugiausia {MAX_SOUND_FORMS}): apribokite krepšį ar formų skaičių.")
    d, table, symbols = sound_clusters.sound_distances(ctx.read, variants, ctx.progress)
    via = Counter(table.sounds[s].via for s in symbols)
    ctx.note(f"Segmentai: {'; '.join(f'{SOURCE_LABELS[k]} – {v}' for k, v in sources.items())}.")
    ctx.note(f"{len(symbols)} skirtingų garsų: BIPA {via.get('bipa', 0)}, kita CLTS sistema {via.get('system', 0)}, "
             f"apytiksliai {via.get('approx', 0)}, neatpažinta {via.get('unknown', 0)}.")
    return {"atstumai": Distances(Items(items.kind, rows, items.data), d, "garsinis atstumas")}


@part("leksinis_artumas", "Matai", title="Leksinis artumas",
      summary="Kokia dalis abiejose kalbose koduotų reikšmių turi bendrą kognatų grupę: S = C / M.",
      inputs=[Port("kalbos", ("items",), label="Kalbos")],
      outputs=[Port("panasumai", ("sim",))],
      params=[Param("min_overlap", "Mažiausiai bendrų reikšmių porai", default=50, min=1, max=500,
                    help="Kiek mažiausiai tų pačių reikšmių turi būti koduota abiem kalbom, kad poros artumas būtų žinomas. "
                         "Menkiau paliudytų porų artumas laikomas nežinomu (grafe jos nejungiamos).")],
      help="M – reikšmės (Concepticon), koduotos abiejose kalbose; C – kiek jų turi bendrą kognatų grupę. Kiekviena "
           "reikšmė skaičiuojama vieną kartą.")
def leksinis_artumas(ctx, inputs, params):
    items: Items = inputs["kalbos"]
    per_lang = items.data.get("per_lang")
    if items.kind != "kalba" or per_lang is None:
        raise ValueError("Leksinis artumas skaičiuojamas kalboms iš šaltinio „Kalbos“.")
    comparable, shared, sim = tree_fit.lexical([per_lang[k] for k in items.keys()])
    s = np.where(comparable >= params["min_overlap"], sim, np.nan)
    np.fill_diagonal(s, 1.0)
    iu = np.triu_indices(len(items), 1)
    known = int(np.isfinite(s[iu]).sum())
    ctx.note(f"Žinomas {known} iš {len(iu[0])} porų artumas (bent {params['min_overlap']} bendrų reikšmių).")
    return {"panasumai": Similarities(items, s, "leksinis artumas", {"comparable": comparable.astype(float), "shared": shared.astype(float)})}


def _lineage(items: Items) -> tuple[list[int], list[dict]]:
    have, langs = [], []
    for i, r in enumerate(items.rows):
        if r.get("_path"):
            have.append(i)
            langs.append({"path": r["_path"], "glottolog": r.get("_glottolog") or r["_path"][-1]})
    return have, langs


@part("genealoginis_atstumas", "Matai", title="Genealoginis atstumas (Glottolog)",
      summary="Kiek toli du vienetai (kalbos ar jų formos) stovi Glottolog medyje.",
      inputs=[Port("vienetai", (ANY,), label="Vienetai")],
      outputs=[Port("atstumai", ("dist",))],
      params=[Param("measure", "Kaip matuoti", "select", "ancestor",
                    options=[("ancestor", "bendro protėvio gylis"), ("edges", "briaunų skaičius medyje")],
                    help="„Bendro protėvio gylis“: kuo giliau medyje artimiausias bendras protėvis, tuo arčiau (0 – giliausias). "
                         "„Briaunų skaičius“: kiek šakų pereiti nuo vieno iki kito – iškraipo, kai šakos nevienodai smulkiai suskaidytos.")],
      help="Skirtingų šeimų vienetų atstumas nežinomas. Vienetai be vietos Glottolog medyje neįtraukiami.")
def genealoginis_atstumas(ctx, inputs, params):
    items: Items = inputs["vienetai"].items
    have, langs = _lineage(items)
    for i in sorted(set(range(len(items))) - set(have)):
        ctx.drop(items.rows[i], "nėra vietos Glottolog medyje")
    if len(have) < 2:
        raise ValueError("Vienetai neturi vietos Glottolog medyje.")
    edges_d, ancestor_d = tree_fit.genealogical(langs)
    d = ancestor_d if params["measure"] == "ancestor" else edges_d
    return {"atstumai": Distances(items.take(have), d, "bendro protėvio gylis" if params["measure"] == "ancestor" else "briaunų skaičius medyje")}


@part("geografinis_atstumas", "Matai", title="Geografinis atstumas",
      summary="Atstumas kilometrais tarp kalbų (ar jų formų) koordinačių, pagal didįjį apskritimą.",
      inputs=[Port("vienetai", (ANY,), label="Vienetai")],
      outputs=[Port("atstumai", ("dist",))],
      help="Koordinatės – kalbos (Glottolog ar duomenyno) platuma ir ilguma. Vienetai be koordinačių neįtraukiami.")
def geografinis_atstumas(ctx, inputs, params):
    items: Items = inputs["vienetai"].items
    have = [i for i, r in enumerate(items.rows) if r.get("lat") is not None and r.get("lon") is not None]
    for i in sorted(set(range(len(items))) - set(have)):
        ctx.drop(items.rows[i], "nėra koordinačių")
    if len(have) < 2:
        raise ValueError("Vienetai neturi koordinačių.")
    lat = np.radians([float(items.rows[i]["lat"]) for i in have])
    lon = np.radians([float(items.rows[i]["lon"]) for i in have])
    a = (np.sin((lat[:, None] - lat[None]) / 2) ** 2
         + np.cos(lat[:, None]) * np.cos(lat[None]) * np.sin((lon[:, None] - lon[None]) / 2) ** 2)
    d = 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return {"atstumai": Distances(items.take(have), d, "kilometrai")}


GROUP_ATTRS = [("language", "kalba"), ("cognate", "kognatų grupė"), ("glottolog_name", "Glottolog kalba"),
               ("field", "semantinis laukas"), ("dataset", "duomenynas")]
LANG_LEVEL = ("glottolog_name", "lat", "lon", "_glottolog", "_path", "_path_names")


@part("sutraukti", "Matai", title="Sutraukti pagal požymį",
      summary="Vienetų poras sujungia į jų požymio (pvz. kalbos) poras: dviejų kalbų atstumas – vidutinis jų formų atstumas.",
      inputs=[Port("matrica", ("dist", "sim"), label="Atstumai / panašumai")],
      outputs=[Port("matrica", (SAME + "matrica",), label="Atstumai / panašumai")],
      params=[Param("attribute", "Požymis", "select", "language", options=GROUP_ATTRS,
                    help="Pagal kurį požymį jungti. Pvz. formų garsinius atstumus sutraukus pagal kalbą gaunami kalbų "
                         "garsiniai atstumai, kuriuos galima lyginti su genealoginiais ar geografiniais.")],
      help="Vienos grupės viduje atstumas laikomas 0 (panašumas – vidutinis). Sutraukus pagal kalbą, nauji vienetai yra "
           "kalbos ir paveldi jų Glottolog vietą bei koordinates.")
def sutraukti(ctx, inputs, params):
    mx = inputs["matrica"]
    items, attr = mx.items, params["attribute"]
    vals = attribute(items, attr)
    groups = sorted({v for v in vals if v is not None}, key=str)
    if len(groups) < 2:
        raise ValueError(f"Požymis „{attr}“ turi mažiau nei dvi reikšmes.")
    gi = {g: i for i, g in enumerate(groups)}
    members = [[i for i, v in enumerate(vals) if v == g] for g in groups]
    n = len(groups)
    out = np.full((n, n), np.nan)
    for a in range(n):
        for b in range(a, n):
            block = mx.m[np.ix_(members[a], members[b])]
            if a == b:
                block = block[~np.eye(len(members[a]), dtype=bool)] if len(members[a]) > 1 else block.ravel()
            v = block[np.isfinite(block)]
            if v.size:
                out[a, b] = out[b, a] = float(v.mean())
    for a in range(n):
        out[a, a] = 0.0 if mx.type == "dist" else (out[a, a] if np.isfinite(out[a, a]) else 1.0)
    rows = []
    for g in groups:
        first = items.rows[members[gi[g]][0]]
        name = first.get(attr) if attr in first else g
        row = {"key": str(g), "name": name, "count": len(members[gi[g]])}
        if attr == "language":
            row.update({k: first.get(k) for k in LANG_LEVEL if k in first})
            row["_label"] = "Languoid"
        rows.append(row)
    kind = {"language": "kalba", "glottolog_name": "kalba"}.get(attr, attr)
    return {"matrica": type(mx)(Items(kind, rows), out, f"{mx.label}, vidurkis pagal {dict(GROUP_ATTRS).get(attr, attr)}")}


@part("panasumas_is_atstumo", "Matai", title="Atstumai → panašumai",
      summary="Panašumas = 1 − atstumas (arba didžiausias atstumas − atstumas).",
      inputs=[Port("atstumai", ("dist",))],
      outputs=[Port("panasumai", ("sim",))],
      params=[Param("scale", "Kaip versti", "select", "one", options=[("one", "1 − atstumas"), ("max", "1 − atstumas / didžiausias")],
                    help="„1 − atstumas“ tinka atstumams nuo 0 iki 1 (garsiniam). Kitiems (km, medžio gyliui) – padalyti iš didžiausio.")])
def panasumas_is_atstumo(ctx, inputs, params):
    d = inputs["atstumai"]
    top = np.nanmax(d.m) if params["scale"] == "max" and np.isfinite(d.m).any() else 1.0
    return {"panasumai": Similarities(d.items, 1 - d.m / (top or 1.0), f"1 − {d.label}")}


@part("atstumas_is_panasumo", "Matai", title="Panašumai → atstumai",
      summary="Atstumas = 1 − panašumas.",
      inputs=[Port("panasumai", ("sim",))],
      outputs=[Port("atstumai", ("dist",))],
      help="Tinka panašumams nuo 0 iki 1 (pvz. leksiniam artumui). Nežinomas panašumas lieka nežinomu atstumu.")
def atstumas_is_panasumo(ctx, inputs, params):
    s = inputs["panasumai"]
    d = 1 - s.m
    np.fill_diagonal(d, 0.0)
    return {"atstumai": Distances(s.items, d, f"1 − {s.label}", s.extra)}
