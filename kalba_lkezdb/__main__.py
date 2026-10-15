"""Komandinė eilutė: python -m kalba_lkezdb explain|include|remove|queue|replan ŽODIS…, counts, delete-all, raktas"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kalba_import.neo4j_config import DEFAULT_NEO4J_CONFIG, neo4j_settings

from . import DEFAULT_DB
from .service import Lkezdb


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kalba_lkezdb", description="LKEŽDB žodžių aiškinimas ir įtraukimas į Neo4j")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--neo4j-config", default=str(DEFAULT_NEO4J_CONFIG))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("explain", "išaiškinti (ir įtraukti, jei nenurodyta --no-include)"), ("include", "įtraukti išsaugotą aiškinimą"),
                       ("remove", "pašalinti žodžio duomenis iš Neo4j"), ("queue", "įdėti į eilę (darbą atlieka veikiantis sodas)"),
                       ("replan", "perdaryti grafo planą iš išsaugoto aiškinimo")):
        p = sub.add_parser(name, help=text)
        p.add_argument("words", nargs="+", help="žodis arba zodziai.GUID")
        if name in ("explain", "queue"):
            p.add_argument("--no-include", action="store_true")
    sub.add_parser("delete-all", help="ištrinti VISUS LKEŽDB duomenis iš Neo4j (kiti duomenynai lieka)")
    sub.add_parser("counts", help="kiek LKEŽDB mazgų ir ryšių yra Neo4j")
    rk = sub.add_parser("raktas", help="kurį API raktą programa naudoja ir iš kur (su --tikrinti – ir ar jis veikia)")
    rk.add_argument("--tikrinti", action="store_true", help="vienas mažytis bandomasis kvietimas")
    args = ap.parse_args(argv)
    lk = Lkezdb(Path(args.db), lambda: neo4j_settings(config_path=Path(args.neo4j_config)))
    out = {}
    if args.cmd == "raktas":
        from .llm import check_key
        print(json.dumps(check_key(lk.store, args.tikrinti), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "delete-all":
        out = lk.delete_all()
    elif args.cmd == "counts":
        out = lk.counts()
    else:
        for w in args.words:
            row = lk.store.find_word(w)
            if not row:
                out[w] = {"error": "žodis nerastas"}
                continue
            g = row["GUID"]
            if args.cmd == "explain":
                out[w] = lk.explain(g)
                if not args.no_include:
                    out[w]["included"] = lk.include(g)
            elif args.cmd == "queue":
                lk.store.enqueue(g, not args.no_include)
                out[w] = {"queued": True}
            else:
                out[w] = getattr(lk, args.cmd)(g)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
