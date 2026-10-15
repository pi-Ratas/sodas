"""Scores (rodikliai): a number for every unit – how well it sits in its group, fits the tree, how stable it is."""
from __future__ import annotations

import numpy as np

from .. import stability
from ..spectral import rankdata, silhouette
from ..tree_fit import _gamma
from .core import Items, Param, Port, Scores, common, part


@part("siluetas", "Rodikliai", title="Siluetas",
      summary="Kiek kiekvienas vienetas arčiau savo grupės nei artimiausios kitos: nuo −1 (ne savo grupėje) iki 1.",
      inputs=[Port("atstumai", ("dist",)), Port("grupes", ("partition",), label="Skaidinys")],
      outputs=[Port("rodikliai", ("scores",))],
      help="Vidutinis siluetas virš 0,5 – grupės ryškios, apie 0 – susiliejančios; neigiamas – vienetas tarp grupių.")
def siluetas(ctx, inputs, params):
    d, p = common(inputs["atstumai"], inputs["grupes"], need=3)
    known = [i for i, g in enumerate(p.labels) if g is not None]
    d, p = d.take(known), p.take(known)
    codes = {g: i for i, g in enumerate(p.groups())}
    s = silhouette(np.nan_to_num(d.m, nan=np.nanmax(d.m)), np.array([codes[g] for g in p.labels]))
    mean = f"{s.mean():.2f}".replace(".", ",")
    ctx.note(f"Vidutinis siluetas {mean}.")
    return {"rodikliai": Scores(d.items, {"silhouette": s}, {"silhouette": {"label": "siluetas", "up": True,
                                                                             "explain": "kiek vienetas arčiau savo grupės nei kitos"}},
                                f"siluetas ({p.label})")}


@part("atitikimas_medziui", "Rodikliai", title="Atitikimas medžiui (γ)",
      summary="Ar vieneto artimiausi pagal vieną matą yra artimiausi ir pagal kitą: Goodman–Kruskal γ kiekvienam vienetui.",
      inputs=[Port("medis", ("dist",), label="Atstumai (pvz. medyje)"),
              Port("kitas", ("dist", "sim"), label="Lyginami (pvz. leksiniai)")],
      outputs=[Port("rodikliai", ("scores",))],
      help="Iš kitų vienetų porų, kurias pirmasis matas išrikiuoja (lygūs praleidžiami), kokia dalis išrikiuota taip pat "
           "ir pagal antrąjį (γ: 1 – visos, 0 – kaip atsitiktinai, −1 – atvirkščiai). Mažas γ – kalba, kurios žodynas "
           "neatitinka jos vietos medyje (kontaktai, skoliniai, duomenų spragos).")
def atitikimas_medziui(ctx, inputs, params):
    a, b = common(inputs["medis"], inputs["kitas"], need=4)
    other = b.m if b.type == "dist" else 1 - b.m
    n = len(a.items)
    fit = np.full(n, np.nan)
    for i in range(n):
        ok = [j for j in range(n) if j != i and np.isfinite(a.m[i, j]) and np.isfinite(other[i, j])]
        g = _gamma(a.m[i, ok], other[i, ok]) if ok else None
        fit[i] = np.nan if g is None else g
    return {"rodikliai": Scores(a.items, {"fit": fit}, {"fit": {"label": "atitikimas medžiui γ", "up": True,
                                                                 "explain": "ar artimiausi pagal vieną matą artimiausi ir pagal kitą"}},
                                f"γ: {a.label} ~ {b.label}")}


FORM_META = {k: {"label": l, "up": u, "side": s, "explain": e} for k, s, l, u, e in stability.COMPONENTS}
# component names without Lithuanian letters, listed so that they are collected for translation
WORDS = {"components": ["Polisemija IE-CoR", "Polisemija DatSemShift"]}


@part("formos_pastovumas", "Rodikliai", title="Formos pastovumas",
      summary="Ar sąvoką visur reiškia tas pats paveldėtas žodis: kognatų išlaikymas, išlikimas tolimose šakose, "
              "leksinio pakeitimo dažnis (Fitch), polisemija IE-CoR.",
      inputs=[Port("savokos", ("items",), label="Sąvokos")],
      outputs=[Port("rodikliai", ("scores",))],
      params=[Param("min_languages", "Mažiausiai kalbų sąvokai", default=20, min=3, max=200,
                    help="Kiek mažiausiai kalbų (turinčių vietą Glottolog medyje) turi turėti kognatais koduotą sąvokos žodį.")],
      help="Kaip tyrime „Sąvokų semantinis pastovumas“. Kalbos – šaltinio „Sąvokos (IE-CoR)“ (krepšio šaka jas apriboja).")
def formos_pastovumas(ctx, inputs, params):
    items: Items = inputs["savokos"]
    if items.kind != "sąvoka":
        raise ValueError("Formos pastovumas skaičiuojamas sąvokoms iš šaltinio „Sąvokos (IE-CoR)“.")
    fs = stability.form_stability(ctx.read, items.data.get("lang_keys"), int(params["min_languages"]), ctx.progress)
    form = fs["form"]
    keep = [i for i, r in enumerate(items.rows) if r["key"] in form]
    for i in sorted(set(range(len(items))) - set(keep)):
        ctx.drop(items.rows[i], "per mažai kalbų", f"Mažiau nei {params['min_languages']} kalbų su kognatais koduotu žodžiu.")
    if not keep:
        raise ValueError("Nė viena sąvoka neturi pakankamai kalbų.")
    sub = items.take(keep)
    cols = {k: np.array([form[r["key"]][k] for r in sub.rows], float) for k in ("retention", "deep", "replacement", "colex")}
    ctx.note(f"{len(fs['paths'])} kalbos, {len(fs['branches'])} šakos.")
    return {"rodikliai": Scores(sub, cols, {k: FORM_META[k] for k in cols}, "formos pastovumas")}


@part("reiksmes_pastovumas", "Rodikliai", title="Reikšmės pastovumas",
      summary="Ar sąvoką supa tos pačios kitos reikšmės: polisemija DatSemShift, kaimynystės pastovumas, spektrinės "
              "padėties pastovumas tarp kalbų šeimų.",
      inputs=[Port("savokos", ("items",), label="Sąvokos", optional=True,
                   help="Neprijungus – visos DatSemShift tinklo sąvokos su Concepticon numeriu.")],
      outputs=[Port("rodikliai", ("scores",))],
      params=[Param("include_derivation", "Skaičiuoti ir derivaciją", "bool", False,
                    help="Tinkle be polisemijos skaičiuoti ir derivaciją. Tinklas tankesnis, bet mažiau grynas."),
              Param("min_families", "Mažiausiai šeimų sąvokai", default=3, min=2, max=50,
                    help="Iš kiek mažiausiai šeimų turi būti paliudyti sąvokos ryšiai, kad būtų skaičiuojamas kaimynystės ir "
                         "spektrinės padėties pastovumas."),
              Param("dims", "Spektrinės erdvės matmenys", default=10, min=2, max=30,
                    help="Kiek pirmųjų Laplaso savųjų vektorių nusako sąvokos padėtį tinkle.")],
      help="Kaip tyrime „Sąvokų semantinis pastovumas“: tinklas išskleidžiamas atsitiktinio klajojimo koordinatėmis; "
           "šeimos požiūriu sąvokos padėtis – jos tos šeimos kaimynų padėčių vidurkis, pastovumas – jų išsibarstymas.")
def reiksmes_pastovumas(ctx, inputs, params):
    ms = stability.meaning_stability(ctx.read, params["include_derivation"], int(params["dims"]), ctx.progress)
    meaning = ms["meaning"]
    if "savokos" in inputs:
        items = inputs["savokos"]
    else:
        ids = sorted(meaning)
        info = {str(r["cid"]): r for r in ctx.read(stability.CONCEPTS, ids=ids)}
        items = Items("sąvoka", [{"key": c, "name": (info.get(c) or {}).get("name") or c, "field": (info.get(c) or {}).get("field") or "—"}
                                 for c in ids])
    keep = [i for i, r in enumerate(items.rows) if r["key"] in meaning]
    for i in sorted(set(range(len(items))) - set(keep)):
        ctx.drop(items.rows[i], "nėra DatSemShift tinkle")
    if not keep:
        raise ValueError("Nė viena sąvoka nėra DatSemShift tinkle.")
    sub = items.take(keep)
    cols = {}
    for k in ("polysemy", "neighborhood", "spectral"):
        vals = []
        for r in sub.rows:
            m = meaning[r["key"]]
            v = m.get(k)
            if k != "polysemy" and m["families"] < params["min_families"]:
                v = None
            vals.append(np.nan if v is None else float(v))
        cols[k] = np.array(vals)
    ctx.note(f"Tinklas: {ms['network_concepts']} sąvokų, {ms['network_links']} ryšių, didžiausia susieta dalis – "
             f"{ms['network_component']}, {ms['families']} šeimų.")
    return {"rodikliai": Scores(sub, cols, {k: FORM_META[k] for k in cols}, "reikšmės pastovumas")}


@part("sujungti_rodiklius", "Rodikliai", title="Sujungti rodiklius",
      summary="Dviejų rodiklių rinkinių stulpeliai sudedami į vieną lentelę (pagal vienetų raktą).",
      inputs=[Port("a", ("scores",), label="Rodikliai A"), Port("b", ("scores",), label="Rodikliai B")],
      outputs=[Port("rodikliai", ("scores",))],
      params=[Param("how", "Kurie vienetai", "select", "left",
                    options=[("left", "visi A vienetai"), ("inner", "tik esantys abiejuose"), ("outer", "esantys bent viename")],
                    help="Kurių vienetų eilutės lieka. Trūkstamos reikšmės – nežinomos.")])
def sujungti_rodiklius(ctx, inputs, params):
    a, b = inputs["a"], inputs["b"]
    ka, kb = a.items.keys(), b.items.keys()
    ia, ib = {k: i for i, k in enumerate(ka)}, {k: i for i, k in enumerate(kb)}
    how = params["how"]
    keys = ka if how == "left" else [k for k in ka if k in ib] if how == "inner" else ka + [k for k in kb if k not in ia]
    if not keys:
        raise ValueError("Rodiklių rinkiniai neturi bendrų vienetų.")
    rows = [a.items.rows[ia[k]] if k in ia else b.items.rows[ib[k]] for k in keys]
    cols, meta = {}, {}
    for src, idx in ((a, ia), (b, ib)):
        for c, v in src.cols.items():
            name = c if c not in cols else f"{c}_2"
            cols[name] = np.array([v[idx[k]] if k in idx else np.nan for k in keys], float)
            meta[name] = src.meta.get(c, {"label": c})
    return {"rodikliai": Scores(Items(a.items.kind, rows, a.items.data), cols, meta, f"{a.label} + {b.label}")}


@part("procentiliai", "Rodikliai", title="Procentiliai",
      summary="Kiekvienas rodiklis paverčiamas procentiliu 0–1, kur 1 – „geriausias“ (pastoviausias); taip visi rodo ta pačia kryptimi.",
      inputs=[Port("rodikliai", ("scores",))],
      outputs=[Port("rodikliai", ("scores",))],
      help="Rodikliai, kur mažiau yra geriau (pvz. pakeitimo dažnis, polisemija), apverčiami. Lygios reikšmės gauna vidutinį rangą.")
def procentiliai(ctx, inputs, params):
    s = inputs["rodikliai"]
    cols, meta = {}, {}
    for c, v in s.cols.items():
        out = np.full(len(v), np.nan)
        ok = np.isfinite(v)
        if ok.sum() >= 2:
            up = s.meta.get(c, {}).get("up")
            rk = rankdata(v[ok] if up is not False else -v[ok])
            out[ok] = (rk - 1) / (ok.sum() - 1)
        cols[c] = out
        meta[c] = {**s.meta.get(c, {}), "up": True, "percentile": True}
    return {"rodikliai": Scores(s.items, cols, meta, f"{s.label}, procentiliai")}
