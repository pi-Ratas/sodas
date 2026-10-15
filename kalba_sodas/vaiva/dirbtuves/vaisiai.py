"""Views (vaisiai): what the page shows. Each returns a fruit {"kind", "data", "tiles", "notes"}; the page draws it with
``VIEWS[kind]`` (static/dirbtuves.js). A tile is {"v": value, "l": what it is}; a note {"title", "text"}."""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from ..spectral import adjusted_rand, labels_for, mantel, silhouette, spearman
from ..tree_fit import _mantel_text
from .core import ANY, ATTR_LABELS, Param, Port, common, part, public_row
from .spektras import as_distances

MAX_POINTS, MAX_MATRIX, MAX_TREE, MAX_ROWS = 3000, 400, 800, 5000


# words of the notes (kept here so that they are translated as whole texts)
WORDS = {"ari": ["beveik sutampa", "gerokai sutampa", "sutampa iš dalies", "beveik nesutampa", "–"],
         "rho": ["labai stipri", "stipri", "vidutinė", "silpna", "beveik jokios", "neįvertinama"]}


def _ari_words(x) -> str:
    a = WORDS["ari"]
    return a[4] if x is None else a[0] if x >= .8 else a[1] if x >= .5 else a[2] if x >= .2 else a[3]


def _rho_words(r) -> str:
    w = WORDS["rho"]
    if r is None:
        return w[5]
    a = abs(r)
    return w[0] if a >= .8 else w[1] if a >= .6 else w[2] if a >= .4 else w[3] if a >= .2 else w[4]


def num(x, d: int = 2) -> str:
    return "–" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}".replace(".", ",")


def rho(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman correlation over the units where both are known."""
    ok = np.isfinite(a) & np.isfinite(b)
    r = spearman(a[ok], b[ok]) if ok.sum() >= 5 else None
    return round(r, 3) if r is not None else None


def pct(x) -> str:
    return "–" if x is None else f"{round(100 * x)} %"


def group_index(p, keys: list[str]) -> tuple[list[int | None], list[dict]]:
    """Group number (largest first) of every key, and the groups {name, size}."""
    order = p.groups()
    num_of = {g: i for i, g in enumerate(order)}
    by_key = dict(zip(p.items.keys(), p.labels))
    size = Counter(g for g in p.labels if g is not None)
    return [num_of.get(by_key.get(k)) for k in keys], [{"name": p.name(g), "size": size[g]} for g in order]


def info(r: dict) -> dict:
    """Attributes shown on hover: the unit's public attributes, short."""
    out = {}
    for k, v in public_row(r).items():
        if k in ("key", "name", "label") or v in (None, "", "—"):
            continue
        out[ATTR_LABELS.get(k, k)] = round(v, 4) if isinstance(v, float) else v if not isinstance(v, str) else v[:120]
    return out


# ---------------------------------------------------------------- maps and spectra
@part("zemelapis", "Vaisiai", view=True, title="Žemėlapis",
      summary="Vienetai plokštumoje pagal išdėstymą, nuspalvinti pagal skaidinį; galima atverti sode.",
      inputs=[Port("isdestymas", ("layout",)), Port("grupes", ("partition",), label="Spalvos", optional=True),
              Port("atstumai", ("dist",), label="Artimiausių kaimynų ryšiai", optional=True)],
      params=[Param("edge_max", "Kaimyno ryšys iki atstumo", default=0.35, min=0, max=100000,
                    help="Prijungus atstumus, kiekvienas vienetas sujungiamas su artimiausiu kaimynu, jei jų atstumas ne didesnis už šį.")],
      help="Užvedus – vieneto požymiai; spustelėjus grupę legendoje – ji paryškinama. „Atverti sode“ sukuria naują sodą su "
           "šiais mazgais tose pačiose vietose ir spalvomis.")
def zemelapis(ctx, inputs, params):
    lay = inputs["isdestymas"]
    if len(lay.items) > MAX_POINTS:
        raise ValueError(f"Žemėlapiui per daug taškų ({len(lay.items)}; daugiausia {MAX_POINTS}).")
    keys = lay.items.keys()
    xy = lay.xy[:, :2] if lay.xy.shape[1] >= 2 else np.c_[lay.xy, np.zeros(len(lay.xy))]
    span = float(np.abs(xy).max()) or 1.0
    g, groups = group_index(inputs["grupes"], keys) if "grupes" in inputs else ([None] * len(keys), [])
    edges = []
    if "atstumai" in inputs:
        d = inputs["atstumai"]
        di = {k: i for i, k in enumerate(d.items.keys())}
        for a, k in enumerate(keys):
            if k not in di:
                continue
            row = d.m[di[k]]
            best = [(row[di[o]], b) for b, o in enumerate(keys) if o != k and o in di and np.isfinite(row[di[o]])]
            if best:
                dist, b = min(best)
                if dist <= params["edge_max"]:
                    edges.append([a, b, round(float(dist), 3)])
    pts = [{"key": r["key"], "name": r.get("name") or r["key"], "x": round(float(x) / span, 4), "y": round(float(y) / span, 4),
            "g": gi, "label": r.get("_label"), "dataset": r.get("dataset"), "info": info(r)}
           for r, (x, y), gi in zip(lay.items.rows, xy, g)]
    return {"kind": "zemelapis", "data": {"points": pts, "groups": groups, "edges": edges, "layout": lay.label,
                                          "grouping": inputs["grupes"].label if "grupes" in inputs else None}}


@part("savosios_reiksmes", "Vaisiai", view=True, title="Savosios reikšmės",
      summary="Laplaso matricos mažiausios savosios reikšmės: didelis šuolis po k-osios rodo, kad grafas skyla į k grupių.",
      inputs=[Port("spektras", ("spectrum",)), Port("grupes", ("partition",), label="Pažymėti k", optional=True)])
def savosios_reiksmes(ctx, inputs, params):
    s = inputs["spektras"]
    vals = [float(v) for v in s.values[:16]]
    gaps = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
    k_auto = max(range(2, min(13, len(vals))), key=lambda k: gaps[k - 1]) if len(vals) > 3 else None
    k = len(inputs["grupes"].groups()) if "grupes" in inputs else None
    notes = []
    if k_auto:
        notes.append({"title": f"Didžiausias tarpas – po {k_auto}-osios savosios reikšmės",
                      "text": f"{num(vals[k_auto - 1], 3)} → {num(vals[k_auto], 3)}. Kuo didesnis toks tarpas, tuo aiškiau grafas "
                              f"skyla į tiek grupių. Nulinių reikšmių tiek, kiek nesujungtų grafo dalių."})
    return {"kind": "savosios", "data": {"values": vals, "k": k, "k_auto": k_auto, "label": s.label},
            "tiles": [{"v": k_auto or "–", "l": "grupių pagal tarpą"}], "notes": notes}


@part("grupiu_skaicius", "Vaisiai", view=True, title="Kiek grupių?",
      summary="Tie patys savieji vektoriai, suskirstyti į 2 … 12 grupių: savųjų reikšmių tarpas, siluetas, sutapimas su kitu skaidiniu.",
      inputs=[Port("spektras", ("spectrum",)), Port("atstumai", ("dist",), label="Siluetui", optional=True),
              Port("palyginti", ("partition",), label="Palyginti su (ARI)", optional=True),
              Port("pasirinkta", ("partition",), label="Pasirinktas k", optional=True)],
      params=[Param("max_k", "Iki kiek grupių", default=12, min=3, max=30)],
      help="Siluetas – kiek grupės atsiskyrusios; ARI – kiek jos sutampa su prijungtu skaidiniu (pvz. kognatais).")
def grupiu_skaicius(ctx, inputs, params):
    s = inputs["spektras"]
    keys = s.items.keys()
    n = len(keys)
    d_idx = ref = None
    if "atstumai" in inputs:
        dk = {k: i for i, k in enumerate(inputs["atstumai"].items.keys())}
        have = [i for i, k in enumerate(keys) if k in dk]
        d_idx = (have, inputs["atstumai"].m[np.ix_([dk[keys[i]] for i in have], [dk[keys[i]] for i in have])])
    if "palyginti" in inputs:
        pk = dict(zip(inputs["palyginti"].items.keys(), inputs["palyginti"].labels))
        ref = [(i, pk[k]) for i, k in enumerate(keys) if pk.get(k) is not None]
    vals = s.values
    rows = []
    for k in range(2, min(int(params["max_k"]), n - 1) + 1):
        lab = labels_for(s.vectors, k)
        row = {"k": k, "gap": round(float(vals[k] - vals[k - 1]), 4) if len(vals) > k else None}
        if d_idx and len(d_idx[0]) > 2:
            row["silhouette"] = round(float(silhouette(np.nan_to_num(d_idx[1], nan=np.nanmax(d_idx[1])), lab[d_idx[0]]).mean()), 3)
        if ref and len(ref) > 2:
            row["ari"] = round(adjusted_rand([int(lab[i]) for i, _ in ref], [g for _, g in ref]), 3)
        rows.append(row)
    chosen = len(inputs["pasirinkta"].groups()) if "pasirinkta" in inputs else None
    tiles = []
    if any("silhouette" in r for r in rows):
        best = max(rows, key=lambda r: r.get("silhouette", -2))
        tiles.append({"v": best["k"], "l": f"grupių – didžiausias siluetas ({num(best['silhouette'])})"})
    if any("ari" in r for r in rows):
        best = max(rows, key=lambda r: r.get("ari", -2))
        tiles.append({"v": best["k"], "l": f"grupių – didžiausias ARI ({num(best['ari'])})"})
    return {"kind": "k_perziura", "data": {"rows": rows, "chosen": chosen,
                                           "reference": inputs["palyginti"].label if "palyginti" in inputs else None},
            "tiles": tiles}


# ---------------------------------------------------------------- matrices and trees
@part("matrica", "Vaisiai", view=True, title="Matrica",
      summary="Atstumai ar panašumai kaip spalvota lentelė, vienetai surikiuoti pagal grupes.",
      inputs=[Port("matrica", ("dist", "sim"), label="Atstumai / panašumai"),
              Port("grupes", ("partition",), label="Rikiuoti pagal", optional=True)],
      help=f"Daugiausia {MAX_MATRIX} vienetų. Tamsiau – arčiau (panašiau); tušti langeliai – nežinoma.")
def matrica(ctx, inputs, params):
    mx = inputs["matrica"]
    keys = mx.items.keys()
    if len(keys) > MAX_MATRIX:
        raise ValueError(f"Matricai per daug vienetų ({len(keys)}; daugiausia {MAX_MATRIX}).")
    g, groups = group_index(inputs["grupes"], keys) if "grupes" in inputs else ([None] * len(keys), [])
    names = [r.get("name") or r["key"] for r in mx.items.rows]
    order = sorted(range(len(keys)), key=lambda i: (g[i] if g[i] is not None else 10 ** 6, str(names[i])))
    m = mx.m[np.ix_(order, order)]
    fin = m[np.isfinite(m) & ~np.eye(len(order), dtype=bool)]
    return {"kind": "matrica", "data": {"names": [names[i] for i in order], "g": [g[i] for i in order], "groups": groups,
                                        "m": [[None if not np.isfinite(v) else round(float(v), 3) for v in row] for row in m],
                                        "type": mx.type, "label": mx.label,
                                        "lo": float(fin.min()) if fin.size else 0.0, "hi": float(fin.max()) if fin.size else 1.0}}


@part("dendrograma", "Vaisiai", view=True, title="Dendrograma",
      summary="Medis su lapais, nuspalvintais pagal skaidinį; kurios grupės medyje vientisos ir kas į jas įsiterpia.",
      inputs=[Port("medis", ("tree",)), Port("grupes", ("partition",), label="Spalvos", optional=True)],
      help=f"Daugiausia {MAX_TREE} lapų. Grupė vientisa, jei medyje yra šaka, kurioje yra visi jos vienetai ir tik jie.")
def dendrograma(ctx, inputs, params):
    t = inputs["medis"]
    n = len(t.items)
    if n > MAX_TREE:
        raise ValueError(f"Dendrogramai per daug lapų ({n}; daugiausia {MAX_TREE}).")
    leaves = {i: [i] for i in range(n)}
    for j, (a, b, h, s) in enumerate(t.merges):
        leaves[n + j] = leaves[int(a)] + leaves[int(b)]
    order = leaves[n + len(t.merges) - 1] if t.merges else list(range(n))
    keys = t.items.keys()
    g, groups = group_index(inputs["grupes"], keys) if "grupes" in inputs else ([None] * n, [])
    fit = []
    if "grupes" in inputs:
        clades = [set(v) for v in leaves.values()]
        for gi, grp in enumerate(groups):
            members = {i for i in range(n) if g[i] == gi}
            if len(members) < 2:
                continue
            smallest = min((c for c in clades if members <= c), key=len)
            intruders = sorted(smallest - members, key=lambda i: str(t.items.rows[i].get("name")))
            fit.append({"group": gi, "size": len(members), "whole": not intruders,
                        "intruders": [t.items.rows[i].get("name") or keys[i] for i in intruders[:20]], "more": max(0, len(intruders) - 20)})
    tiles, notes = [], []
    if fit:
        whole = sum(1 for f in fit if f["whole"])
        tiles.append({"v": f"{whole} / {len(fit)}", "l": "grupių medyje vientisos"})
        if whole < len(fit):
            notes.append({"title": "Nevientisos grupės", "text": "; ".join(
                f"{groups[f['group']]['name']}: įsiterpia {', '.join(f['intruders'][:6])}{'…' if len(f['intruders']) > 6 or f['more'] else ''}"
                for f in fit if not f["whole"])[:1500]})
    return {"kind": "dendrograma", "data": {"merges": [[int(a), int(b), round(float(h), 4)] for a, b, h, _ in t.merges], "order": order,
                                            "names": [r.get("name") or r["key"] for r in t.items.rows], "g": g, "groups": groups,
                                            "fit": fit, "label": t.label},
            "tiles": tiles, "notes": notes}


# ---------------------------------------------------------------- tables
@part("lentele", "Vaisiai", view=True, title="Vienetų lentelė",
      summary="Visi vienetai su požymiais, grupe ir rodikliais; rikiuojama ir filtruojama.",
      inputs=[Port("vienetai", (ANY,), label="Vienetai"), Port("grupes", ("partition",), label="Grupė", optional=True),
              Port("rodikliai", ("scores",), label="Rodikliai", optional=True)],
      help=f"Daugiausia {MAX_ROWS} eilučių.")
def lentele(ctx, inputs, params):
    obj = inputs["vienetai"]
    items = obj.items
    rows = items.rows[:MAX_ROWS]
    keys = [r["key"] for r in rows]
    attrs = []
    for r in rows:
        for k in public_row(r):
            if k not in attrs and k not in ("key", "label"):
                attrs.append(k)
    cols = [{"key": a, "label": ATTR_LABELS.get(a, a), "num": all(isinstance(r.get(a), (int, float)) or r.get(a) is None for r in rows)} for a in attrs]
    data = [[(round(r.get(a), 4) if isinstance(r.get(a), float) else r.get(a)) for a in attrs] for r in rows]
    if "grupes" in inputs:
        g, groups = group_index(inputs["grupes"], keys)
        cols.append({"key": "grupe", "label": "grupė", "num": True, "group": True})
        for row, gi in zip(data, g):
            row.append(gi)
    else:
        groups = []
    sc = inputs.get("rodikliai") or (obj if obj.type == "scores" else None)
    if sc is not None:
        idx = {k: i for i, k in enumerate(sc.items.keys())}
        for c, v in sc.cols.items():
            cols.append({"key": c, "label": sc.meta.get(c, {}).get("label", c), "num": True, "score": True,
                         "percentile": bool(sc.meta.get(c, {}).get("percentile"))})
            for row, k in zip(data, keys):
                x = v[idx[k]] if k in idx else np.nan
                row.append(round(float(x), 4) if np.isfinite(x) else None)
    if len(items) > MAX_ROWS:
        ctx.note(f"Parodyta {MAX_ROWS} iš {len(items)}.")
    return {"kind": "lentele", "data": {"columns": cols, "rows": data, "groups": groups, "labels": [r.get("_label") for r in rows],
                                        "keys": keys}}


@part("kryzmine", "Vaisiai", view=True, title="Kryžminė lentelė",
      summary="Kiek kiekvienos A grupės vienetų patenka į kiekvieną B grupę; ARI ir grynumas.",
      inputs=[Port("a", ("partition",), label="Skaidinys A (eilutės)"), Port("b", ("partition",), label="Skaidinys B (stulpeliai)")],
      help="ARI (pakoreguotas Rand indeksas): 1 – skaidiniai sutampa, 0 – ne daugiau nei atsitiktinai. Grynumas – kokia dalis "
           "vienetų yra savo A grupės daugiausiai B grupėje.")
def kryzmine(ctx, inputs, params):
    a, b = common(inputs["a"], inputs["b"], need=3)
    both = [i for i in range(len(a.labels)) if a.labels[i] is not None and b.labels[i] is not None]
    if len(both) < 3:
        raise ValueError("Per mažai vienetų, turinčių grupę abiejuose skaidiniuose.")
    la, lb = [a.labels[i] for i in both], [b.labels[i] for i in both]
    ari = adjusted_rand(la, lb)
    ra, cb = a.groups(), b.groups()
    rows_g, cols_g = ra[:25], cb[:15]
    table = [[sum(1 for x, y in zip(la, lb) if x == r and y == c) for c in cols_g] for r in rows_g]
    pure = sum(Counter(y for x, y in zip(la, lb) if x == r).most_common(1)[0][1] for r in set(la)) / len(la)
    splits = []
    for c in cb:
        parts = Counter(x for x, y in zip(la, lb) if y == c)
        if sum(parts.values()) >= 4 and len(parts) > 1 and parts.most_common(2)[1][1] >= 2:
            splits.append(f"„{b.name(c)}“ ({sum(parts.values())}) – " + ", ".join(f"{a.name(x)}: {m}" for x, m in parts.most_common(4)))
    notes = [{"title": f"Skaidiniai {_ari_words(ari)} (ARI {num(ari)})",
              "text": [f"„{a.label}“ ir „{b.label}“; lyginama {len(both)} vienetų.",
                       f"Grynumas {pct(pure)}: grupės beveik nesimaišo." if pure >= .8 else f"Grynumas {pct(pure)}: dalis grupių mišrios."]}]
    if splits:
        notes.append({"title": "Kurios B grupės skyla į kelias A grupes", "text": "; ".join(splits[:4]) + "."})
    return {"kind": "kryzmine", "data": {"rows": [a.name(r) for r in rows_g], "columns": [b.name(c) for c in cols_g], "table": table,
                                         "a": a.label, "b": b.label, "more_rows": max(0, len(ra) - 25), "more_cols": max(0, len(cb) - 15)},
            "tiles": [{"v": num(ari), "l": "ARI"}, {"v": pct(pure), "l": "grynumas"}, {"v": len(both), "l": "vienetų"}], "notes": notes}


@part("grupiu_korteles", "Vaisiai", view=True, title="Grupių kortelės",
      summary="Kiekviena grupė: dydis, tipiškiausias vienetas (medoidas), pavyzdžiai, kiek artima viduje ir iki kitų, sudėtis.",
      inputs=[Port("grupes", ("partition",), label="Skaidinys"), Port("atstumai", ("dist", "sim"), label="Atstumai / panašumai", optional=True),
              Port("sudetis", ("partition",), label="Sudėtis pagal", optional=True,
                   help="Pvz. kognatai ar šakos: kiek kiekvienos grupės vienetų priklauso kiekvienai jų grupei.")])
def grupiu_korteles(ctx, inputs, params):
    p = inputs["grupes"]
    keys = p.items.keys()
    g, groups = group_index(p, keys)
    d = None
    if "atstumai" in inputs:
        mx = inputs["atstumai"]
        dk = {k: i for i, k in enumerate(mx.items.keys())}
        d = (dk, as_distances(mx))
    comp = dict(zip(inputs["sudetis"].items.keys(), inputs["sudetis"].labels)) if "sudetis" in inputs else None
    cards = []
    for gi, grp in enumerate(groups[:40]):
        idx = [i for i in range(len(keys)) if g[i] == gi]
        names = [p.items.rows[i].get("name") or keys[i] for i in idx]
        card = {"g": gi, "name": grp["name"], "size": len(idx), "examples": names[:8]}
        if d is not None:
            have = [i for i in idx if keys[i] in d[0]]
            others = [d[0][k] for j, k in enumerate(keys) if g[j] != gi and k in d[0]]
            if have:
                sub = d[1][np.ix_([d[0][keys[i]] for i in have], [d[0][keys[i]] for i in have])]
                med = have[int(sub.sum(1).argmin())]
                order = sorted(have, key=lambda i: d[1][d[0][keys[med]], d[0][keys[i]]])
                card.update({"medoid": p.items.rows[med].get("name") or keys[med],
                             "examples": [p.items.rows[i].get("name") or keys[i] for i in order[:8]],
                             "intra": round(float(sub[np.triu_indices(len(have), 1)].mean()), 3) if len(have) > 1 else 0.0,
                             "inter": round(float(d[1][np.ix_([d[0][keys[i]] for i in have], others)].mean()), 3) if others else None})
        if comp is not None:
            c = Counter(comp.get(keys[i]) for i in idx)
            card["composition"] = [[inputs["sudetis"].name(k), v] for k, v in c.most_common(6)]
        card["members"] = names[:300]
        cards.append(card)
    return {"kind": "grupes", "data": {"cards": cards, "label": p.label,
                                       "composition": inputs["sudetis"].label if "sudetis" in inputs else None,
                                       "more": max(0, len(groups) - 40)}}


# ---------------------------------------------------------------- comparing two measures
@part("mantel", "Vaisiai", view=True, title="Dviejų matų palyginimas (Mantel)",
      summary="Ar dviejų matų poros eina išvien: Spearman ρ per visas poras ir Mantel permutacijų testas.",
      inputs=[Port("a", ("dist", "sim"), label="Matas A"), Port("b", ("dist", "sim"), label="Matas B")],
      params=[Param("permutations", "Perstatų", default=999, min=0, max=9999,
                    help="Kiek kartų atsitiktinai sumaišyti vienetus, kad būtų įvertinta p reikšmė. 0 – p neskaičiuojama.")],
      help="Panašumai paverčiami atstumais (1 − s), todėl teigiamas ρ visada reiškia, kad matai sutaria. Lyginamos tik "
           "poros, kurių abu matai žinomi. Grafike – A reikšmės pagal B (dėžės, jei B turi nedaug skirtingų reikšmių).")
def mantel_view(ctx, inputs, params):
    a, b = common(inputs["a"], inputs["b"], need=4)
    da = a.m if a.type == "dist" else 1 - a.m
    db = b.m if b.type == "dist" else 1 - b.m
    perms = int(params["permutations"])
    if perms:
        ctx.progress(f"Mantel testas ({perms} perstatų)…")
    rho, p = mantel(da, db, perms)
    iu = np.triu_indices(len(a.items), 1)
    va, vb = a.m[iu], b.m[iu]
    ok = np.isfinite(va) & np.isfinite(vb)
    va, vb = va[ok], vb[ok]
    distinct = np.unique(vb)
    boxes = []
    if 1 < len(distinct) <= 30:
        for x in distinct:
            v = va[vb == x]
            q1, med, q3 = np.percentile(v, [25, 50, 75])
            boxes.append({"x": float(x), "n": int(len(v)), "q1": float(q1), "med": float(med), "q3": float(q3), "min": float(v.min()), "max": float(v.max())})
    rng = np.random.default_rng(0)
    pick = rng.choice(len(va), size=min(3000, len(va)), replace=False) if len(va) else []
    words = _rho_words(rho)
    notes = [{"title": f"Koreliacijos beveik nėra (ρ = {num(rho)})" if words == WORDS["rho"][4] else f"Koreliacija {words} (ρ = {num(rho)})",
              "text": [f"„{a.label}“ ir „{b.label}“: {int(ok.sum())} porų."] + ([_mantel_text(p, perms).strip()] if p is not None else [])
              + ["Poros nėra nepriklausomos (kiekvienas vienetas dalyvauja daugelyje), todėl p imamas iš permutacijų, ne iš formulės."]}]
    return {"kind": "mantel", "data": {"a": a.label, "b": b.label, "a_type": a.type, "b_type": b.type, "boxes": boxes,
                                       "points": [[round(float(vb[i]), 4), round(float(va[i]), 4)] for i in pick]},
            "tiles": [{"v": num(rho), "l": "Spearman ρ"}, {"v": num(p, 3) if p is not None else "–", "l": "Mantel p"},
                      {"v": int(ok.sum()), "l": "porų"}], "notes": notes}


@part("netiketos_poros", "Vaisiai", view=True, title="Netikėtos poros",
      summary="Poros, kurių panašumas daug didesnis ar mažesnis, nei tikėtina jų atstumui: skirtingų grupių, bet panašios "
              "(galimi kontaktai), ir tos pačios grupės, bet tolimos.",
      inputs=[Port("panasumai", ("sim",)), Port("atstumai", ("dist",), label="Atstumai (pvz. medyje)"),
              Port("grupes", ("partition",), label="Grupės (pvz. šakos)")],
      help="Tikėtinas panašumas – visų porų tuo pačiu atstumu mediana (tolydiems atstumams – 12 vienodo dydžio intervalų).")
def netiketos_poros(ctx, inputs, params):
    s, d, p = common(inputs["panasumai"], inputs["atstumai"], inputs["grupes"], need=4)
    n = len(s.items)
    iu = np.triu_indices(n, 1)
    ok = np.isfinite(s.m[iu]) & np.isfinite(d.m[iu])
    dv = d.m[iu][ok]
    if not dv.size:
        raise ValueError("Nėra porų, kurių abu matai žinomi.")
    distinct = np.unique(dv)
    if len(distinct) <= 30:
        bin_of = lambda x: float(x)
    else:
        edges = np.unique(np.quantile(dv, np.linspace(0, 1, 13)))
        bin_of = lambda x: float(edges[min(len(edges) - 2, max(0, int(np.searchsorted(edges, x, side="right")) - 1))])
    groups = defaultdict(list)
    for i, j in zip(*iu):
        if np.isfinite(s.m[i, j]) and np.isfinite(d.m[i, j]):
            groups[bin_of(d.m[i, j])].append(float(s.m[i, j]))
    expected = {k: float(np.median(v)) for k, v in groups.items()}
    res = []
    for i, j in zip(*iu):
        if np.isfinite(s.m[i, j]) and np.isfinite(d.m[i, j]):
            res.append((float(s.m[i, j]) - expected[bin_of(d.m[i, j])], int(i), int(j)))
    res.sort()
    name = lambda i: s.items.rows[i].get("name") or s.items.rows[i]["key"]
    pair = lambda r: {"a": name(r[1]), "b": name(r[2]), "ga": p.name(p.labels[r[1]]), "gb": p.name(p.labels[r[2]]),
                      "sim": round(s.m[r[1], r[2]], 3), "expected": round(expected[bin_of(d.m[r[1], r[2]])], 3),
                      "residual": round(r[0], 3), "dist": round(float(d.m[r[1], r[2]]), 3)}
    same = lambda r: p.labels[r[1]] is not None and p.labels[r[1]] == p.labels[r[2]]
    closer = [pair(r) for r in reversed(res) if r[0] > 0 and p.labels[r[1]] is not None and p.labels[r[2]] is not None and not same(r)][:15]
    farther = [pair(r) for r in res if r[0] < 0 and same(r)][:15]
    return {"kind": "poros", "data": {"closer": closer, "farther": farther, "sim": s.label, "dist": d.label, "groups": p.label}}


@part("medzio_lygiai", "Vaisiai", view=True, title="Atitikimas medžio lygiams",
      summary="Su kuriuo Glottolog medžio lygiu (šeima, šaka, pošakis …) skaidinys sutampa labiausiai (ARI kiekvienam lygiui).",
      inputs=[Port("grupes", ("partition",), label="Skaidinys")],
      help="Vienetai turi turėti vietą Glottolog medyje (formos ar kalbos). Lygiai skaičiuojami nuo visų bendro protėvio.")
def medzio_lygiai(ctx, inputs, params):
    from ..tree_fit import branch_levels
    p = inputs["grupes"]
    have = [i for i, r in enumerate(p.items.rows) if r.get("_path") and p.labels[i] is not None]
    if len(have) < 3:
        raise ValueError("Skaidinio vienetai neturi vietos Glottolog medyje.")
    paths = [p.items.rows[i]["_path"] for i in have]
    names = [p.items.rows[i].get("_path_names") or p.items.rows[i]["_path"] for i in have]
    depth0, _ = branch_levels(paths)
    labels = [p.labels[i] for i in have]
    levels = []
    for lv in range(depth0 + 1, min(max(len(x) for x in paths), depth0 + 9)):
        tags = [x[min(lv, len(x) - 1)] for x in paths]
        levels.append({"level": lv - depth0, "clades": len(set(tags)), "ari": round(adjusted_rand(labels, tags) or 0, 3),
                       "examples": [c for c, _ in Counter(nm[min(lv, len(nm) - 1)] for nm in names).most_common(4)]})
    if not levels:
        raise ValueError("Medyje nėra lygių žemiau bendro protėvio.")
    best = max(levels, key=lambda x: x["ari"])
    return {"kind": "lygiai", "data": {"levels": levels, "label": p.label, "ancestor": names[0][depth0]},
            "tiles": [{"v": best["level"], "l": f"labiausiai atitinkantis lygis (ARI {num(best['ari'])}, {best['clades']} šakos)"}],
            "notes": [{"title": f"Skaidinys su medžiu {_ari_words(best['ari'])} {best['level']}-ame lygyje",
                       "text": f"Žemiau „{names[0][depth0]}“ {best['level']}-ame lygyje yra {best['clades']} šakos (pvz. "
                               f"{', '.join(best['examples'])}); ARI {num(best['ari'])}."}]}


# ---------------------------------------------------------------- scores
def _score_pairs(sc):
    keys = [k for k, v in sc.cols.items() if np.isfinite(v).sum() >= 5]
    return keys


@part("koreliacijos", "Vaisiai", view=True, title="Rodiklių koreliacijos",
      summary="Ar rodikliai pasakoja tą pačią istoriją: Spearman koreliacijos ir pagrindinės komponentės (ar pagrįsta jungti į vieną indeksą).",
      inputs=[Port("rodikliai", ("scores",))],
      help="Jungti į vieną indeksą siūloma, jei pirmoji pagrindinė komponentė paaiškina ≥ 50 % ir visi rodikliai į ją įeina ta pačia kryptimi.")
def koreliacijos(ctx, inputs, params):
    sc = inputs["rodikliai"]
    keys = _score_pairs(sc)
    if len(keys) < 2:
        raise ValueError("Reikia bent dviejų rodiklių su ≥ 5 žinomomis reikšmėmis.")
    corr = [[rho(sc.cols[a], sc.cols[b]) for b in keys] for a in keys]
    full = np.all([np.isfinite(sc.cols[k]) for k in keys], axis=0)
    pca = None
    if full.sum() >= max(8, len(keys) + 2):
        x = np.array([sc.cols[k][full] for k in keys]).T
        x = (x - x.mean(0)) / np.where(x.std(0) > 0, x.std(0), 1)
        vals, vecs = np.linalg.eigh(np.cov(x.T))
        o = np.argsort(vals)[::-1]
        vals, vecs = vals[o], vecs[:, o]
        load = vecs[:, 0] * (1 if vecs[:, 0].sum() >= 0 else -1)
        pca = {"explained": [round(float(v / vals.sum()), 3) for v in vals], "loadings": [round(float(v), 3) for v in load],
               "units": int(full.sum()), "same_sign": bool(np.all(load > 0.1) or np.all(load < -0.1))}
    labels = [sc.meta.get(k, {}).get("label", k) for k in keys]
    notes = []
    if pca:
        join = pca["explained"][0] >= 0.5 and pca["same_sign"]
        notes.append({"title": "Jungti į vieną indeksą pagrįsta" if join else "Jungti į vieną indeksą nepagrįsta",
                      "text": [f"Pirmoji pagrindinė komponentė paaiškina {pct(pca['explained'][0])} ({pca['units']} vienetų su visais rodikliais).",
                               "Visi rodikliai į ją įeina ta pačia kryptimi." if pca["same_sign"] else "Rodikliai į ją įeina skirtingomis kryptimis."]})
    return {"kind": "koreliacijos", "data": {"keys": keys, "labels": labels, "corr": corr, "pca": pca}, "notes": notes,
            "tiles": [{"v": pct(pca["explained"][0]) if pca else "–", "l": "paaiškina 1-oji komponentė"}]}


@part("grupiu_testas", "Vaisiai", view=True, title="Grupių permutacijų testas",
      summary="Ar kurios nors grupės (pvz. semantiniai laukai) vidutinis rodiklis didesnis ar mažesnis, nei būtų atsitiktinai.",
      inputs=[Port("rodikliai", ("scores",)), Port("grupes", ("partition",), label="Grupės")],
      params=[Param("permutations", "Perstatų", default=2000, min=100, max=20000),
              Param("alpha", "Reikšmingumo riba", default=0.05, min=0.0001, max=0.5)],
      help="Grupės vidurkis lyginamas su tiek pat atsitiktinai paimtų vienetų vidurkiais. Tiriamos grupės su ≥ 3 vienetais.")
def grupiu_testas(ctx, inputs, params):
    sc, p = common(inputs["rodikliai"], inputs["grupes"], need=5)
    keys = _score_pairs(sc)
    rng = np.random.default_rng(0)
    perms, alpha = int(params["permutations"]), params["alpha"]
    out = []
    for g in p.groups():
        members = [i for i, x in enumerate(p.labels) if x == g]
        if len(members) < 3:
            continue
        tests = {}
        for k in keys:
            v = sc.cols[k]
            vals = v[np.isfinite(v)]
            mine = v[members][np.isfinite(v[members])]
            if len(mine) < 3 or len(vals) <= len(mine):
                continue
            obs = float(mine.mean())
            null = np.array([rng.choice(vals, size=len(mine), replace=False).mean() for _ in range(perms)])
            tests[k] = {"mean": round(obs, 3), "all": round(float(vals.mean()), 3), "n": int(len(mine)),
                        "p_high": round(float((np.sum(null >= obs) + 1) / (perms + 1)), 4),
                        "p_low": round(float((np.sum(null <= obs) + 1) / (perms + 1)), 4)}
        if tests:
            out.append({"group": p.name(g), "size": len(members), "tests": tests})
    labels = {k: sc.meta.get(k, {}).get("label", k) for k in keys}
    alpha_text = f"{alpha:g}".replace(".", ",")
    hits = [f"{o['group']} – {labels[k]} ({'daugiau' if t['p_high'] < alpha else 'mažiau'}, p {num(min(t['p_high'], t['p_low']), 3)})"
            for o in out for k, t in o["tests"].items() if min(t["p_high"], t["p_low"]) < alpha]
    return {"kind": "grupiu_testas", "data": {"groups": out, "keys": keys, "labels": labels, "alpha": alpha, "grouping": p.label},
            "tiles": [{"v": len(hits), "l": f"reikšmingų skirtumų (p < {alpha:g})".replace(".", ",")}],
            "notes": [{"title": "Reikšmingai išsiskiria" if hits else "Nė viena grupė reikšmingai neišsiskiria",
                       "text": ["; ".join(hits[:12]) + "." if hits else "Skirtumai neviršija to, kas būtų atsitiktinai.",
                                f"Tikrinant daug grupių ir rodiklių, kelis „reikšmingus“ galima gauti atsitiktinai (riba {alpha_text})."]}]}


@part("sklaida", "Vaisiai", view=True, title="Dviejų rodiklių sklaida",
      summary="Kiekvienas vienetas – taškas pagal du rodiklius; ketvirčiai pagal medianas (pvz. forma pastovi, reikšmė kinta).",
      inputs=[Port("rodikliai", ("scores",)), Port("grupes", ("partition",), label="Spalvos", optional=True)],
      params=[Param("x", "X rodiklis", "text", "", help="Rodiklio vardas (pvz. retention); tuščia – pirmasis."),
              Param("y", "Y rodiklis", "text", "", help="Tuščia – antrasis.")])
def sklaida(ctx, inputs, params):
    sc = inputs["rodikliai"]
    keys = list(sc.cols)
    if len(keys) < 2:
        raise ValueError("Reikia bent dviejų rodiklių.")
    x = params["x"] or keys[0]
    y = params["y"] or keys[1]
    for c in (x, y):
        if c not in sc.cols:
            raise ValueError(f"Nėra rodiklio „{c}“. Galimi: {', '.join(keys)}.")
    vx, vy = sc.cols[x], sc.cols[y]
    ok = np.isfinite(vx) & np.isfinite(vy)
    ukeys = sc.items.keys()
    g, groups = group_index(inputs["grupes"], ukeys) if "grupes" in inputs else ([None] * len(ukeys), [])
    pts = [{"name": sc.items.rows[i].get("name") or ukeys[i], "x": round(float(vx[i]), 4), "y": round(float(vy[i]), 4), "g": g[i],
            "info": info(sc.items.rows[i])} for i in np.flatnonzero(ok)]
    mx, my = (float(np.median(vx[ok])), float(np.median(vy[ok]))) if ok.any() else (0, 0)
    quad = {"hh": [], "hl": [], "lh": [], "ll": []}
    for pnt in sorted(pts, key=lambda q: -abs(q["x"] - mx) - abs(q["y"] - my)):
        quad[("h" if pnt["x"] >= mx else "l") + ("h" if pnt["y"] >= my else "l")].append(pnt["name"])
    lx, ly = sc.meta.get(x, {}).get("label", x), sc.meta.get(y, {}).get("label", y)
    return {"kind": "sklaida", "data": {"points": pts, "x": lx, "y": ly, "mx": mx, "my": my, "groups": groups,
                                        "quadrants": {k: v[:10] for k, v in quad.items()}},
            "tiles": [{"v": num(rho(vx, vy)), "l": f"Spearman ρ ({lx} ~ {ly})"}]}


@part("uzrasas", "Vaisiai", view=True, title="Užrašas",
      summary="Jūsų tekstas tarp vaisių: kam ši sąranka, ką tikrinate, ką pastebėjote.",
      params=[Param("text", "Tekstas", "text", "", help="Iki 400 ženklų.")])
def uzrasas(ctx, inputs, params):
    return {"kind": "uzrasas", "data": {"text": params["text"] or ""}}
