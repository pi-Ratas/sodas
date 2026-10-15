"""Spectral analysis and the other ways to group, place and order the units."""
from __future__ import annotations

import numpy as np

from .. import tree_fit
from ..spectral import classical_mds, eigengap_k, labels_for, laplacian_spectrum, signed_embedding, upgma
from .core import ANY, Items, Layout, Param, Partition, Port, Spectrum, Tree, attribute, part


@part("laplaso_spektras", "Spektrinė analizė", title="Laplaso spektras",
      summary="Normalizuotos Laplaso matricos L = I − D^-½ W D^-½ savosios reikšmės ir vektoriai.",
      inputs=[Port("grafas", ("graph",))],
      outputs=[Port("spektras", ("spectrum",))],
      help="Mažos savosios reikšmės ir jų vektoriai nusako stambią grafo sandarą: kiek nulinių reikšmių – tiek atskirų "
           "gabalų, didelis tarpas po k-osios – grafas skyla į k grupių.")
def laplaso_spektras(ctx, inputs, params):
    g = inputs["grafas"]
    if len(g.items) < 3:
        raise ValueError("Per mažai vienetų spektrui.")
    vals, vecs = laplacian_spectrum(g.m)
    zeros = int(np.sum(vals < 1e-9))
    if zeros > 1:
        ctx.note(f"Grafas susideda iš {zeros} nesujungtų dalių: pirmosios {zeros} savosios reikšmės lygios 0. "
                 "Gal verta prijungti „Didžiausia susieta grafo dalis“.")
    return {"spektras": Spectrum(g.items, vals, vecs, g, g.label)}


@part("spektrines_grupes", "Spektrinė analizė", title="Spektrinės grupės",
      summary="Vienetai suskirstomi į k grupių: k-vidurkiai pirmųjų k savųjų vektorių erdvėje (Ng, Jordan, Weiss).",
      inputs=[Port("spektras", ("spectrum",)),
              Port("k_kaip", ("partition",), label="Tiek grupių, kiek čia", optional=True,
                   help="Prijungus kitą skaidinį, grupių imama tiek pat, kiek jame (pvz. medžio grafą skaidyti į tiek "
                        "grupių, kiek rado leksinis).")],
      outputs=[Port("grupes", ("partition",), label="Skaidinys")],
      params=[Param("k", "Grupių skaičius", default=None, min=2, max=30, hint="tuščia – pagal savųjų reikšmių tarpą",
                    help="Tuščia – parenkama ten, kur didžiausias tarpas tarp gretimų savųjų reikšmių."),
              Param("max_k", "Didžiausias renkamas k", default=12, min=2, max=30,
                    help="Kai k parenkamas pats, ieškoma tarp 2 ir šio skaičiaus.")])
def spektrines_grupes(ctx, inputs, params):
    s = inputs["spektras"]
    k_auto, gaps = eigengap_k(s.values, int(params["max_k"]))
    if "k_kaip" in inputs:
        k = len(inputs["k_kaip"].groups())
    else:
        k = int(params["k"] or k_auto)
    k = max(1, min(k, len(s.items) - 1, 30))
    labels = labels_for(s.vectors, k)
    ctx.note(f"{k} grupės (pagal savųjų reikšmių tarpą būtų {k_auto})." if k != k_auto else f"{k} grupės – pagal savųjų reikšmių tarpą.")
    return {"grupes": Partition(s.items, [str(int(v)) for v in labels], {str(i): str(i + 1) for i in range(k)},
                                f"spektrinės grupės ({s.label})",
                                {"k": k, "k_auto": k_auto, "gaps": gaps[:15], "eigenvalues": [float(v) for v in s.values[:16]], "spectral": True})}


@part("spektrinis_isdestymas", "Spektrinė analizė", title="Spektrinis išdėstymas",
      summary="Vienetų vietos pagal 2-ąjį ir 3-iąjį savuosius vektorius.",
      inputs=[Port("spektras", ("spectrum",))],
      outputs=[Port("isdestymas", ("layout",))],
      help="Ženklas parenkamas taip, kad didžiausia koordinatė būtų teigiama (kad kartojant būtų tas pats). Medžio grafų "
           "spektriniai žemėlapiai dažnai sutraukia daug vienetų į kelis taškus – tada aiškesnis MDS.")
def spektrinis_isdestymas(ctx, inputs, params):
    s = inputs["spektras"]
    return {"isdestymas": Layout(s.items, signed_embedding(s.vectors), f"spektrinis ({s.label})")}


def as_distances(mx) -> np.ndarray:
    """A distance matrix of distances or similarities, unknown → just beyond the largest."""
    d = mx.m if mx.type == "dist" else 1 - mx.m
    finite = d[np.isfinite(d)]
    top = float(finite.max()) if finite.size else 1.0
    fill = 1.0 if finite.size and finite.min() >= 0 and top <= 1 else top + 1
    d = np.where(np.isfinite(d), d, fill)
    np.fill_diagonal(d, 0)
    return d


@part("mds", "Spektrinė analizė", title="Daugiamatis skalavimas (MDS)",
      summary="Vienetų vietos plokštumoje, kuo geriau išlaikančios jų atstumus (klasikinis MDS).",
      inputs=[Port("matrica", ("dist", "sim"), label="Atstumai / panašumai")],
      outputs=[Port("isdestymas", ("layout",))],
      help="Panašumai paverčiami atstumais 1 − s. Nežinomi atstumai laikomi didžiausiais.")
def mds(ctx, inputs, params):
    mx = inputs["matrica"]
    return {"isdestymas": Layout(mx.items, classical_mds(as_distances(mx)), f"MDS ({mx.label})")}


@part("upgma", "Spektrinė analizė", title="Medis (UPGMA)",
      summary="Hierarchinis medis: artimiausi vienetai ir grupės jungiami pirmi (vidutinės jungties metodas).",
      inputs=[Port("matrica", ("dist", "sim"), label="Atstumai / panašumai")],
      outputs=[Port("medis", ("tree",))],
      help="Panašumai paverčiami atstumais 1 − s. Daugiau nei ~1500 vienetų skaičiuoti ilgai.")
def upgma_part(ctx, inputs, params):
    mx = inputs["matrica"]
    if len(mx.items) > 2000:
        raise ValueError("Medžiui per daug vienetų (daugiausia 2000).")
    ctx.progress("Statomas medis…")
    return {"medis": Tree(mx.items, [[int(a), int(b), float(h), int(s)] for a, b, h, s in upgma(as_distances(mx))], f"UPGMA ({mx.label})")}


LEVELS = [("auto", "pirmas lygis su 3 … n/2 šakų"), ("split", "pirmas skilimas")] + [(str(i), f"{i}-as lygis žemiau bendro protėvio") for i in range(1, 7)]


@part("glottolog_sakos", "Spektrinė analizė", title="Glottolog šakos",
      summary="Vienetai suskirstomi pagal Glottolog šaką, kuriai priklauso jų kalba.",
      inputs=[Port("vienetai", (ANY,), label="Vienetai")],
      outputs=[Port("sakos", ("partition",), label="Skaidinys")],
      params=[Param("level", "Medžio lygis", "select", "auto", options=LEVELS,
                    help="Lygiai skaičiuojami nuo visų vienetų bendro protėvio. „Pirmas lygis su 3 … n/2 šakų“ – kaip "
                         "„Kalbų medžio“ tyrime; „pirmas skilimas“ – pirmasis lygis, kuriame vienetai išsiskiria.")],
      help="Vienetai be vietos Glottolog medyje lieka be grupės.")
def glottolog_sakos(ctx, inputs, params):
    items: Items = inputs["vienetai"].items
    have = [i for i, r in enumerate(items.rows) if r.get("_path")]
    if len(have) < 2:
        raise ValueError("Vienetai neturi vietos Glottolog medyje.")
    paths = [items.rows[i]["_path"] for i in have]
    depth0, auto = tree_fit.branch_levels(paths)
    lv = auto if params["level"] == "auto" else depth0 + 1 if params["level"] == "split" else depth0 + int(params["level"])
    labels: list[str | None] = [None] * len(items)
    names = {}
    for i in have:
        r = items.rows[i]
        p, pn = r["_path"], r.get("_path_names") or r["_path"]
        labels[i] = p[min(lv, len(p) - 1)]
        names[labels[i]] = pn[min(lv, len(pn) - 1)]
    top = items.rows[have[0]].get("_path_names") or paths[0]
    ancestor = top[depth0] if all(len(p) > depth0 and p[depth0] == paths[0][depth0] for p in paths) else None
    ctx.note(f"{lv - depth0}-as lygis žemiau „{ancestor or '?'}“: {len(set(x for x in labels if x))} šakos.")
    return {"sakos": Partition(items, labels, names, "Glottolog šakos", {"level": lv - depth0, "ancestor": ancestor, "depth0": depth0})}


@part("pagal_pozymi", "Spektrinė analizė", title="Skaidinys pagal požymį",
      summary="Vienetai suskirstomi pagal požymį: kognatų grupę, kalbą, semantinį lauką, duomenyną …",
      inputs=[Port("vienetai", (ANY,), label="Vienetai")],
      outputs=[Port("skaidinys", ("partition",))],
      params=[Param("attribute", "Požymis", "text", "cognate",
                    help="Požymio vardas: cognate (IE-CoR kognatų grupė), language, dataset, glottolog_name, field "
                         "(semantinis laukas), focus, reconstructed …")],
      help="Taip gaunamas palyginimo pagrindas: ar spektrinės grupės sutampa su kognatais, šakomis, laukais.")
def pagal_pozymi(ctx, inputs, params):
    items: Items = inputs["vienetai"].items
    attr = params["attribute"]
    vals = attribute(items, attr)
    names = {}
    for r, v in zip(items.rows, vals):
        if v is not None:
            names.setdefault(str(v), str(r.get(attr) if r.get(attr) is not None else v))
    labels = [str(v) if v not in (None, "", "—") else None for v in vals]
    return {"skaidinys": Partition(items, labels, names, ATTR_NAMES.get(attr, attr))}


ATTR_NAMES = {"cognate": "kognatų grupės", "language": "kalbos", "field": "semantiniai laukai", "dataset": "duomenynai",
              "glottolog_name": "Glottolog kalbos", "focus": "krepšyje", "reconstructed": "rekonstruota"}
