"""Ready setups (receptai): the three studies of Vaiva put together from parts, and a few new combinations.
They open in the workshop like any setup and can be changed there."""
from __future__ import annotations

from typing import Any

COL = [40, 300, 560, 820, 1080, 1360]


def _setup(blocks: list[tuple], links: list[tuple]) -> dict[str, Any]:
    """blocks: (id, part, column, row, params); links: (from block, port, to block, port)."""
    return {"blocks": [{"id": b, "type": t, "x": COL[c], "y": 30 + 120 * r, "params": p} for b, t, c, r, p in blocks],
            "links": [{"from": [a, ap], "to": [b, bp]} for a, ap, b, bp in links]}


SOUND = _setup(
    [("krepsys", "krepsys", 0, 0, {}), ("formos", "formos", 0, 1, {}), ("atstumai", "garsinis_atstumas", 1, 1, {}),
     ("grafas", "gauso_branduolys", 2, 1, {}), ("spektras", "laplaso_spektras", 3, 1, {}), ("grupes", "spektrines_grupes", 4, 1, {}),
     ("mds", "mds", 2, 0, {}), ("kognatai", "pagal_pozymi", 1, 3, {"attribute": "cognate"}),
     ("sakos", "glottolog_sakos", 1, 4, {"level": "split"}), ("siluetas", "siluetas", 4, 3, {}),
     ("v_zemelapis", "zemelapis", 5, 0, {}), ("v_savosios", "savosios_reiksmes", 5, 1, {}), ("v_k", "grupiu_skaicius", 5, 2, {}),
     ("v_korteles", "grupiu_korteles", 5, 3, {}), ("v_kognatai", "kryzmine", 5, 4, {}), ("v_sakos", "kryzmine", 5, 5, {}),
     ("v_matrica", "matrica", 5, 6, {}), ("v_lentele", "lentele", 5, 7, {})],
    [("krepsys", "krepsys", "formos", "krepsys"), ("formos", "formos", "atstumai", "formos"), ("atstumai", "atstumai", "grafas", "atstumai"),
     ("grafas", "grafas", "spektras", "grafas"), ("spektras", "spektras", "grupes", "spektras"), ("atstumai", "atstumai", "mds", "matrica"),
     ("atstumai", "atstumai", "kognatai", "vienetai"), ("atstumai", "atstumai", "sakos", "vienetai"),
     ("atstumai", "atstumai", "siluetas", "atstumai"), ("grupes", "grupes", "siluetas", "grupes"),
     ("mds", "isdestymas", "v_zemelapis", "isdestymas"), ("grupes", "grupes", "v_zemelapis", "grupes"), ("atstumai", "atstumai", "v_zemelapis", "atstumai"),
     ("spektras", "spektras", "v_savosios", "spektras"), ("grupes", "grupes", "v_savosios", "grupes"),
     ("spektras", "spektras", "v_k", "spektras"), ("atstumai", "atstumai", "v_k", "atstumai"), ("kognatai", "skaidinys", "v_k", "palyginti"),
     ("grupes", "grupes", "v_k", "pasirinkta"),
     ("grupes", "grupes", "v_korteles", "grupes"), ("atstumai", "atstumai", "v_korteles", "atstumai"), ("kognatai", "skaidinys", "v_korteles", "sudetis"),
     ("grupes", "grupes", "v_kognatai", "a"), ("kognatai", "skaidinys", "v_kognatai", "b"),
     ("grupes", "grupes", "v_sakos", "a"), ("sakos", "sakos", "v_sakos", "b"),
     ("atstumai", "atstumai", "v_matrica", "matrica"), ("grupes", "grupes", "v_matrica", "grupes"),
     ("atstumai", "atstumai", "v_lentele", "vienetai"), ("grupes", "grupes", "v_lentele", "grupes"), ("siluetas", "rodikliai", "v_lentele", "rodikliai")])

TREE = _setup(
    [("krepsys", "krepsys", 0, 0, {}), ("kalbos", "kalbos", 0, 1, {}), ("leksinis", "leksinis_artumas", 1, 0, {"min_overlap": 50}),
     ("medis", "genealoginis_atstumas", 1, 3, {"measure": "ancestor"}), ("lgrafas", "panasumu_grafas", 2, 0, {}),
     ("dalis", "didziausia_dalis", 3, 0, {}), ("lspektras", "laplaso_spektras", 4, 0, {}), ("lgrupes", "spektrines_grupes", 4, 1, {}),
     ("lex", "apriboti", 2, 1, {}), ("gen", "apriboti", 2, 3, {}), ("ggrafas", "eksponentinis_svoris", 3, 3, {"tau": 4}),
     ("gspektras", "laplaso_spektras", 3, 4, {}), ("ggrupes", "spektrines_grupes", 4, 4, {}),
     ("sakos", "glottolog_sakos", 3, 2, {"level": "auto"}), ("lmds", "mds", 3, 1, {}), ("gmds", "mds", 4, 3, {}),
     ("upgma", "upgma", 2, 2, {}), ("gama", "atitikimas_medziui", 2, 5, {}),
     ("v_mantel", "mantel", 5, 0, {"permutations": 999}), ("v_savosios", "savosios_reiksmes", 5, 1, {}),
     ("v_lygiai", "medzio_lygiai", 5, 2, {}), ("v_lzem", "zemelapis", 5, 3, {}), ("v_gzem", "zemelapis", 5, 4, {}),
     ("v_dendro", "dendrograma", 5, 5, {}), ("v_kryz", "kryzmine", 5, 6, {}), ("v_poros", "netiketos_poros", 5, 7, {}),
     ("v_matrica", "matrica", 5, 8, {}), ("v_lentele", "lentele", 5, 9, {}), ("v_glygiai", "medzio_lygiai", 4, 6, {})],
    [("krepsys", "krepsys", "kalbos", "krepsys"), ("kalbos", "kalbos", "leksinis", "kalbos"), ("kalbos", "kalbos", "medis", "vienetai"),
     ("leksinis", "panasumai", "lgrafas", "panasumai"), ("lgrafas", "grafas", "dalis", "grafas"), ("dalis", "grafas", "lspektras", "grafas"),
     ("lspektras", "spektras", "lgrupes", "spektras"),
     ("leksinis", "panasumai", "lex", "ka"), ("dalis", "grafas", "lex", "pagal"), ("medis", "atstumai", "gen", "ka"), ("dalis", "grafas", "gen", "pagal"),
     ("gen", "ka", "ggrafas", "atstumai"), ("ggrafas", "grafas", "gspektras", "grafas"), ("gspektras", "spektras", "ggrupes", "spektras"),
     ("lgrupes", "grupes", "ggrupes", "k_kaip"),
     ("dalis", "grafas", "sakos", "vienetai"), ("lex", "ka", "lmds", "matrica"), ("gen", "ka", "gmds", "matrica"), ("lex", "ka", "upgma", "matrica"),
     ("gen", "ka", "gama", "medis"), ("lex", "ka", "gama", "kitas"),
     ("lex", "ka", "v_mantel", "a"), ("gen", "ka", "v_mantel", "b"),
     ("lspektras", "spektras", "v_savosios", "spektras"), ("lgrupes", "grupes", "v_savosios", "grupes"),
     ("lgrupes", "grupes", "v_lygiai", "grupes"), ("ggrupes", "grupes", "v_glygiai", "grupes"),
     ("lmds", "isdestymas", "v_lzem", "isdestymas"), ("sakos", "sakos", "v_lzem", "grupes"),
     ("gmds", "isdestymas", "v_gzem", "isdestymas"), ("sakos", "sakos", "v_gzem", "grupes"),
     ("upgma", "medis", "v_dendro", "medis"), ("sakos", "sakos", "v_dendro", "grupes"),
     ("lgrupes", "grupes", "v_kryz", "a"), ("sakos", "sakos", "v_kryz", "b"),
     ("lex", "ka", "v_poros", "panasumai"), ("gen", "ka", "v_poros", "atstumai"), ("sakos", "sakos", "v_poros", "grupes"),
     ("lex", "ka", "v_matrica", "matrica"), ("sakos", "sakos", "v_matrica", "grupes"),
     ("dalis", "grafas", "v_lentele", "vienetai"), ("sakos", "sakos", "v_lentele", "grupes"), ("gama", "rodikliai", "v_lentele", "rodikliai")])

STABILITY = _setup(
    [("krepsys", "krepsys", 0, 0, {}), ("savokos", "savokos", 0, 1, {}),
     ("forma", "formos_pastovumas", 1, 0, {"min_languages": 20}),
     ("reiksme", "reiksmes_pastovumas", 1, 2, {"min_families": 3, "dims": 10}),
     ("kartu", "sujungti_rodiklius", 2, 1, {"how": "left"}), ("proc", "procentiliai", 3, 1, {}),
     ("laukai", "pagal_pozymi", 3, 3, {"attribute": "field"}),
     ("v_kor", "koreliacijos", 5, 0, {}), ("v_test", "grupiu_testas", 5, 1, {}),
     ("v_skl", "sklaida", 5, 2, {"x": "retention", "y": "spectral"}), ("v_lentele", "lentele", 5, 3, {})],
    [("krepsys", "krepsys", "savokos", "krepsys"), ("savokos", "savokos", "forma", "savokos"), ("savokos", "savokos", "reiksme", "savokos"),
     ("forma", "rodikliai", "kartu", "a"), ("reiksme", "rodikliai", "kartu", "b"), ("kartu", "rodikliai", "proc", "rodikliai"),
     ("proc", "rodikliai", "laukai", "vienetai"),
     ("proc", "rodikliai", "v_kor", "rodikliai"), ("proc", "rodikliai", "v_test", "rodikliai"), ("laukai", "skaidinys", "v_test", "grupes"),
     ("proc", "rodikliai", "v_skl", "rodikliai"), ("laukai", "skaidinys", "v_skl", "grupes"),
     ("proc", "rodikliai", "v_lentele", "vienetai"), ("laukai", "skaidinys", "v_lentele", "grupes")])

SOUND_LANGS = _setup(
    [("krepsys", "krepsys", 0, 0, {}), ("formos", "formos", 0, 1, {}), ("garsai", "garsinis_atstumas", 1, 1, {}),
     ("kalbu", "sutraukti", 2, 1, {"attribute": "language"}), ("medis", "genealoginis_atstumas", 3, 0, {}),
     ("geo", "geografinis_atstumas", 3, 2, {}), ("mds", "mds", 3, 1, {}), ("sakos", "glottolog_sakos", 4, 1, {"level": "auto"}),
     ("v_medis", "mantel", 5, 0, {"permutations": 999}), ("v_geo", "mantel", 5, 1, {"permutations": 999}),
     ("v_zem", "zemelapis", 5, 2, {"edge_max": 1}), ("v_matrica", "matrica", 5, 3, {})],
    [("krepsys", "krepsys", "formos", "krepsys"), ("formos", "formos", "garsai", "formos"), ("garsai", "atstumai", "kalbu", "matrica"),
     ("kalbu", "matrica", "medis", "vienetai"), ("kalbu", "matrica", "geo", "vienetai"), ("kalbu", "matrica", "mds", "matrica"),
     ("kalbu", "matrica", "sakos", "vienetai"),
     ("kalbu", "matrica", "v_medis", "a"), ("medis", "atstumai", "v_medis", "b"), ("kalbu", "matrica", "v_geo", "a"), ("geo", "atstumai", "v_geo", "b"),
     ("mds", "isdestymas", "v_zem", "isdestymas"), ("sakos", "sakos", "v_zem", "grupes"), ("kalbu", "matrica", "v_zem", "atstumai"),
     ("kalbu", "matrica", "v_matrica", "matrica"), ("sakos", "sakos", "v_matrica", "grupes")])

LEX_GEO = _setup(
    [("krepsys", "krepsys", 0, 0, {}), ("kalbos", "kalbos", 0, 1, {}), ("leksinis", "leksinis_artumas", 1, 0, {"min_overlap": 50}),
     ("geo", "geografinis_atstumas", 1, 2, {}), ("medis", "genealoginis_atstumas", 1, 3, {}), ("sakos", "glottolog_sakos", 2, 3, {"level": "auto"}),
     ("v_geo", "mantel", 5, 0, {"permutations": 999}), ("v_medis", "mantel", 5, 1, {"permutations": 999}),
     ("v_poros", "netiketos_poros", 5, 2, {})],
    [("krepsys", "krepsys", "kalbos", "krepsys"), ("kalbos", "kalbos", "leksinis", "kalbos"), ("kalbos", "kalbos", "geo", "vienetai"),
     ("kalbos", "kalbos", "medis", "vienetai"), ("kalbos", "kalbos", "sakos", "vienetai"),
     ("leksinis", "panasumai", "v_geo", "a"), ("geo", "atstumai", "v_geo", "b"),
     ("leksinis", "panasumai", "v_medis", "a"), ("medis", "atstumai", "v_medis", "b"),
     ("leksinis", "panasumai", "v_poros", "panasumai"), ("geo", "atstumai", "v_poros", "atstumai"), ("sakos", "sakos", "v_poros", "grupes")])

RECIPES = [
    {"id": "garsiniai-klasteriai", "title": "Formų garsinio panašumo spektrinė klasterizacija",
     "summary": "Krepšio sąvokų formos grupuojamos pagal tai, kaip panašiai skamba; grupės lyginamos su kognatais ir šakomis.",
     "setup": SOUND},
    {"id": "kalbu-medis", "title": "Kalbų leksinis artumas ir genealoginis medis",
     "summary": "Ar kalbos, kurios dalijasi daugiau kognatų, ir Glottolog medyje stovi arčiau? Krepšys nebūtinas.",
     "setup": TREE},
    {"id": "semantinis-pastovumas", "title": "Sąvokų semantinis pastovumas",
     "summary": "Formos ir reikšmės pastovumo rodikliai, jų koreliacijos ir semantinių laukų testai. Krepšys nebūtinas.",
     "setup": STABILITY},
    {"id": "garsiniai-kalbu-atstumai", "title": "Garsiniai kalbų atstumai, medis ir geografija",
     "summary": "Formų garsiniai atstumai sutraukiami į kalbų atstumus ir lyginami su Glottolog medžiu bei geografija.",
     "setup": SOUND_LANGS},
    {"id": "leksika-ir-geografija", "title": "Leksinis artumas ir geografija",
     "summary": "Ar kaimyninės kalbos dalijasi daugiau kognatų nei tolimos? Lyginama su geografija ir su medžiu; netikėtai artimos poros.",
     "setup": LEX_GEO},
]
