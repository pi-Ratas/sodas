"""Filters (sietai) of units: by an attribute, by a group, by the units of another input."""
from __future__ import annotations

import numpy as np

from .core import ANY, SAME, Param, Port, align, part

OPS = [("eq", "lygu"), ("ne", "nelygu"), ("has", "turi tekstą"), ("not_has", "neturi teksto"),
       ("ge", "≥"), ("le", "≤"), ("set", "žinomas"), ("unset", "nežinomas")]


def _test(op: str, value, wanted: str) -> bool:
    if op == "set":
        return value not in (None, "", "—")
    if op == "unset":
        return value in (None, "", "—")
    if value is None:
        return op == "ne"
    if op in ("ge", "le"):
        try:
            x, w = float(value), float(str(wanted).replace(",", "."))
        except (TypeError, ValueError):
            return False
        return x >= w if op == "ge" else x <= w
    v, w = str(value).lower(), str(wanted or "").lower()
    if op == "eq":
        return v == w or v in [x.strip() for x in w.split(";")]
    if op == "ne":
        return v != w and v not in [x.strip() for x in w.split(";")]
    if op == "has":
        return w in v
    return w not in v


@part("vienetu_sietas", "Sietai", title="Vienetų sietas",
      summary="Palieka vienetus, kurių požymis atitinka sąlygą (pvz. kalba = Lithuanian; rekonstruota = ne; grupė = 2).",
      inputs=[Port("ka", (ANY,), label="Ką sijoti"),
              Port("skaidinys", ("partition",), label="Grupės", optional=True,
                   help="Prijungus skaidinį, galima sijoti pagal požymį „grupė“ (grupės numeris, kaip vaisiuose).")],
      outputs=[Port("ka", (SAME + "ka",), label="Kas lieka")],
      params=[Param("attribute", "Požymis", "text", "language",
                    help="Vieneto požymio vardas: language, cognate, dataset, reconstructed, glottolog_name, field, focus, "
                         "meanings, languages, name, key; su skaidiniu – grupė. Vienetų lentelėje matomi visi požymiai."),
              Param("op", "Sąlyga", "select", "eq", options=OPS,
                    help="„lygu“ ir „nelygu“ priima kelias reikšmes, atskirtas kabliataškiu; didžiosios ir mažosios raidės nesvarbios."),
              Param("value", "Reikšmė", "text", "", help="Su kuo lyginti (sąlygoms „žinomas“ ir „nežinomas“ nereikia).")],
      help="Sietas veikia bet kurį duomenų tipą, turintį vienetus: vienetus, atstumus, grafą, skaidinį, rodiklius. Spektro "
           "ir medžio sijoti negalima – sijokite prieš juos.")
def vienetu_sietas(ctx, inputs, params):
    obj = inputs["ka"]
    rows = obj.items.rows
    attr, op, wanted = params["attribute"], params["op"], params["value"]
    if attr == "grupė":
        if "skaidinys" not in inputs:
            raise ValueError("Požymiui „grupė“ prijunkite skaidinį.")
        p = inputs["skaidinys"]
        number = {g: str(i + 1) for i, g in enumerate(p.groups())}
        by_key = {k: number.get(g) for k, g in zip(p.items.keys(), p.labels)}
        values = [by_key.get(r["key"]) for r in rows]
    else:
        if not any(attr in r for r in rows):
            have = sorted({k for r in rows for k in r if not k.startswith("_")})
            raise ValueError(f"Vienetai neturi požymio „{attr}“. Galimi: {', '.join(have)}.")
        values = [r.get(attr) for r in rows]
    keep = [i for i, v in enumerate(values) if _test(op, v, wanted)]
    if not keep:
        raise ValueError("Pro sietą nepraėjo nė vienas vienetas.")
    ctx.note(f"Liko {len(keep)} iš {len(rows)}.")
    return {"ka": obj if len(keep) == len(rows) else obj.take(keep)}


@part("apriboti", "Sietai", title="Apriboti pagal kitą",
      summary="Palieka tik tuos vienetus, kurie yra ir kitame įėjime (pvz. medžio atstumus – tik leksinio grafo kalboms).",
      inputs=[Port("ka", (ANY,), label="Ką apriboti"), Port("pagal", (ANY,), label="Pagal ką")],
      outputs=[Port("ka", (SAME + "ka",), label="Kas lieka")],
      help="Vienetai atpažįstami pagal raktą (formos, kalbos, Concepticon sąvokos). Tvarka lieka pirmojo įėjimo.")
def apriboti(ctx, inputs, params):
    obj, other = inputs["ka"], inputs["pagal"]
    keys, (idx, _) = align(obj, other)
    if not keys:
        raise ValueError("Įėjimai neturi bendrų vienetų.")
    idx = np.sort(idx)
    ctx.note(f"Liko {len(idx)} iš {len(obj.items)}.")
    return {"ka": obj if len(idx) == len(obj.items) else obj.take(idx)}
