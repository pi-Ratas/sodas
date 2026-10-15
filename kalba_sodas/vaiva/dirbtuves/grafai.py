"""Graphs: from distances or similarities to a weighted graph, and filters of a graph."""
from __future__ import annotations

import numpy as np

from ..spectral import affinity
from ..tree_fit import _largest_component
from .core import Graph, Param, Port, part


@part("gauso_branduolys", "Grafai", title="Gauso branduolys (savaime derinamas)",
      summary="Atstumai → grafas: artimi vienetai jungiami stipriai, tolimi – silpnai; mastas kiekvienam vienetui savas.",
      inputs=[Port("atstumai", ("dist",))],
      outputs=[Port("grafas", ("graph",))],
      params=[Param("knn", "Kaimynų skaičius masteliui", default=7, min=1, max=50,
                    help="Kiekvieno vieneto mastas σᵢ – atstumas iki tiek artimiausio kaimyno (Zelnik-Manor ir Perona, 2004). "
                         "Svoris exp(−d² / σᵢσⱼ). Mažesnis – grafas labiau skyla į tankias grupes.")],
      help="Taip garsinių atstumų matrica paverčiama grafu spektrinei analizei. Nežinomi atstumai laikomi labai dideliais.")
def gauso_branduolys(ctx, inputs, params):
    d = inputs["atstumai"]
    if len(d.items) < 3:
        raise ValueError("Per mažai vienetų grafui.")
    m = np.where(np.isfinite(d.m), d.m, np.nanmax(d.m) * 10 if np.isfinite(d.m).any() else 1.0)
    w = affinity(m, int(params["knn"]))
    return {"grafas": Graph(d.items, w, f"Gauso branduolys ({d.label})")}


@part("eksponentinis_svoris", "Grafai", title="Svoris exp(−atstumas / τ)",
      summary="Atstumai → grafas: ryšys silpsta eksponentiškai, kuo toliau vienetai.",
      inputs=[Port("atstumai", ("dist",))],
      outputs=[Port("grafas", ("graph",))],
      params=[Param("tau", "Mastas τ", default=4, min=0.001, max=100000,
                    help="Kaip greitai silpsta ryšys. Mažas τ – jungiami beveik vien artimiausi, didelis – ir tolimi. "
                         "Medžio gyliui tinka 2–8, kilometrams – šimtai.")],
      help="Nežinomi atstumai (pvz. skirtingų šeimų kalbos) ryšio neturi.")
def eksponentinis_svoris(ctx, inputs, params):
    d = inputs["atstumai"]
    w = np.where(np.isfinite(d.m), np.exp(-np.nan_to_num(d.m, nan=1e12) / params["tau"]), 0.0)
    np.fill_diagonal(w, 0)
    return {"grafas": Graph(d.items, w, f"exp(−{d.label} / {params['tau']:g})")}


@part("panasumu_grafas", "Grafai", title="Panašumai → grafas",
      summary="Panašumas tampa ryšio svoriu; nežinomi ir mažesni už slenkstį panašumai ryšio neduoda.",
      inputs=[Port("panasumai", ("sim",))],
      outputs=[Port("grafas", ("graph",))],
      params=[Param("threshold", "Slenkstis", default=0, min=0, max=1000000,
                    help="Mažesni panašumai laikomi nuliu. 0 – imami visi žinomi.")])
def panasumu_grafas(ctx, inputs, params):
    s = inputs["panasumai"]
    w = np.where(np.isfinite(s.m) & (s.m >= params["threshold"]), np.clip(np.nan_to_num(s.m), 0, None), 0.0)
    np.fill_diagonal(w, 0)
    return {"grafas": Graph(s.items, w, s.label)}


@part("didziausia_dalis", "Sietai", title="Didžiausia susieta grafo dalis",
      summary="Palieka tik didžiausią susietą grafo dalį; atskirti vienetai neįtraukiami.",
      inputs=[Port("grafas", ("graph",))],
      outputs=[Port("grafas", ("graph",))],
      help="Spektrinė analizė prasminga susietam grafui: atskiri gabalai duotų po nulinę savąją reikšmę ir „grupes“, "
           "kurios tėra atskirti gabalai.")
def didziausia_dalis(ctx, inputs, params):
    g = inputs["grafas"]
    part_ = sorted(_largest_component(g.m))
    for i in sorted(set(range(len(g.items))) - set(part_)):
        ctx.drop(g.items.rows[i], "ne didžiausioje susietoje dalyje", "Su kitais vienetais grafe nesujungtas (arba tik su mažu gabalu).")
    if len(part_) < 3:
        raise ValueError(f"Didžiausia susieta dalis turi tik {len(part_)} vienetus: grafe beveik nėra ryšių. Leksiniam artumui "
                         "sumažinkite „Mažiausiai bendrų reikšmių porai“ arba neimkite krepšio sąvokų (jos apriboja reikšmes).")
    return {"grafas": g.take(part_)}


@part("stipriausi_rysiai", "Sietai", title="Stipriausi ryšiai",
      summary="Kiekvienam vienetui palieka tik k stipriausių ryšių (retina tankų grafą).",
      inputs=[Port("grafas", ("graph",))],
      outputs=[Port("grafas", ("graph",))],
      params=[Param("k", "Ryšių vienetui", default=10, min=1, max=200,
                    help="Ryšys paliekamas, jei jis tarp k stipriausių bent vieno iš dviejų vienetų.")])
def stipriausi_rysiai(ctx, inputs, params):
    g = inputs["grafas"]
    k = int(params["k"])
    keep = np.zeros_like(g.m, dtype=bool)
    for i in range(len(g.m)):
        top = np.argsort(-g.m[i])[:k]
        keep[i, top[g.m[i, top] > 0]] = True
    keep |= keep.T
    return {"grafas": Graph(g.items, np.where(keep, g.m, 0.0), f"{g.label}, {k} stipriausi")}
