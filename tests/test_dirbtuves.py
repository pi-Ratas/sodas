"""Vaivos dirbtuvės: the parts, the checking and running of a setup, the ready setups."""
import copy
import json
import re
import unittest
from pathlib import Path

import numpy as np

from kalba_sodas.vaiva import dirbtuves, tree_fit
from kalba_sodas.vaiva.dirbtuves import core
from kalba_sodas.vaiva.dirbtuves.core import PARTS, TYPES, Distances, Items, Partition, check_setup, execute
from tests.test_vaiva import TreeFitTests, fake_tree_read

STATIC = Path(__file__).resolve().parent.parent / "kalba_sodas" / "static"


def setup(blocks, links):
    return {"blocks": [{"id": b, "type": t, "params": p, "x": 0, "y": i * 100} for i, (b, t, p) in enumerate(blocks)],
            "links": [{"from": [a, ap], "to": [b, bp]} for a, ap, b, bp in links]}


class CatalogTests(unittest.TestCase):
    def test_parts_are_well_formed(self):
        for p in PARTS.values():
            self.assertIn(p.group, core.GROUPS)
            for port in p.inputs + p.outputs:
                for t in port.types:
                    self.assertTrue(t in TYPES or t == core.ANY or (t.startswith(core.SAME) and t[1:] in [i.name for i in p.inputs]),
                                    f"{p.id}.{port.name}: {t}")
            self.assertEqual(p.view, not p.outputs, p.id)
            self.assertEqual(len({x.name for x in p.inputs}), len(p.inputs), p.id)
        json.dumps(dirbtuves.workshop())

    def test_every_fruit_kind_has_a_view_on_the_page(self):
        js = (STATIC / "dirbtuves.js").read_text(encoding="utf-8")
        views = set(re.findall(r"^  (\w+)\(D, el", js, flags=re.M))
        src = "".join(p.read_text(encoding="utf-8") for p in (Path(dirbtuves.__file__).parent).glob("*.py"))
        kinds = set(re.findall(r'"kind": "(\w+)"', src))
        self.assertTrue(kinds)
        self.assertLessEqual(kinds, views, f"be piešimo: {kinds - views}")

    def test_recipes_are_valid_setups(self):
        for r in dirbtuves.RECIPES:
            s = check_setup(r["setup"])
            self.assertTrue(any(PARTS[b["type"]].view for b in s["blocks"]), r["id"])


class CheckTests(unittest.TestCase):
    def test_bad_setups(self):
        with self.assertRaisesRegex(ValueError, "Nežinoma detalė"):
            check_setup(setup([("a", "nera", {})], []))
        with self.assertRaisesRegex(ValueError, "tokio lizdo"):
            check_setup(setup([("a", "kalbos", {}), ("b", "mds", {})], [("a", "kalbos", "b", "nera")]))
        with self.assertRaisesRegex(ValueError, "viena jungtis"):
            check_setup(setup([("a", "kalbos", {}), ("k", "kalbos", {}), ("b", "apriboti", {})],
                              [("a", "kalbos", "b", "ka"), ("k", "kalbos", "b", "ka")]))
        with self.assertRaisesRegex(ValueError, "ratas"):
            check_setup(setup([("a", "apriboti", {}), ("b", "apriboti", {})], [("a", "ka", "b", "ka"), ("b", "ka", "a", "ka")]))

    def test_unknown_params_are_dropped_and_defaults_kept(self):
        s = check_setup(setup([("a", "leksinis_artumas", {"min_overlap": 7, "x": 1})], []))
        self.assertEqual(s["blocks"][0]["params"], {"min_overlap": 7})

    def test_param_limits(self):
        p = next(q for q in PARTS["leksinis_artumas"].params if q.name == "min_overlap")
        self.assertEqual(p.clean(None), 50)
        with self.assertRaises(ValueError):
            p.clean(0)


class RunTests(unittest.TestCase):
    def setUp(self):
        core.clear_cache()
        self.read = fake_tree_read(TreeFitTests().data())

    def test_tree_recipe_gives_the_study_numbers(self):
        recipe = copy.deepcopy(next(r for r in dirbtuves.RECIPES if r["id"] == "kalbu-medis")["setup"])
        for b in recipe["blocks"]:
            if b["type"] == "leksinis_artumas":
                b["params"]["min_overlap"] = 5
            elif b["type"] == "mantel":
                b["params"]["permutations"] = 49
        r = dirbtuves.run(self.read, [], {"setup": recipe}, {})
        old = tree_fit.run(self.read, [], {"min_overlap": 5, "permutations": 49}, {})
        self.assertEqual(r["summary"]["errors"], 0, r["blocks"])
        mantel = next(f for f in r["fruits"] if f["part"] == "mantel")
        self.assertEqual(mantel["tiles"][0]["v"], f"{old['summary']['rho']:.2f}".replace(".", ","))
        self.assertIn("ne didžiausioje susietoje dalyje", [d["reason"] for d in r["dropped"]])
        dendro = next(f for f in r["fruits"] if f["part"] == "dendrograma")
        self.assertEqual({x["whole"] for x in dendro["data"]["fit"]}, {True})
        json.dumps(r)
        # the same again: every block from the cache
        again = dirbtuves.run(self.read, [], {"setup": recipe}, {})
        self.assertTrue(all(s.get("cached") for s in again["blocks"].values()))

    def test_a_failing_block_does_not_stop_the_others(self):
        s = check_setup(setup(
            [("k", "kalbos", {}), ("g", "garsinis_atstumas", {}), ("m", "mds", {}), ("z", "zemelapis", {}),
             ("gen", "genealoginis_atstumas", {}), ("m2", "mds", {}), ("z2", "zemelapis", {}), ("t", "lentele", {})],
            [("k", "kalbos", "g", "formos"), ("g", "atstumai", "m", "matrica"), ("m", "isdestymas", "z", "isdestymas"),
             ("k", "kalbos", "gen", "vienetai"), ("gen", "atstumai", "m2", "matrica"), ("m2", "isdestymas", "z2", "isdestymas")]))
        r = execute(self.read, [], s, {})
        self.assertEqual(r["blocks"]["g"]["status"], "error")
        self.assertIn("tik formoms", r["blocks"]["g"]["error"])
        self.assertEqual(r["blocks"]["m"]["status"], "skipped")
        self.assertEqual(r["blocks"]["t"]["status"], "error")          # its input is not connected
        self.assertIn("Neprijungta", r["blocks"]["t"]["error"])
        self.assertEqual(r["blocks"]["z2"]["status"], "ok")
        self.assertEqual([f["block"] for f in r["fruits"]], ["z2"])

    def test_a_setup_without_fruits_is_refused(self):
        with self.assertRaisesRegex(ValueError, "vaisiaus"):
            dirbtuves.run(self.read, [], {"setup": setup([("k", "kalbos", {})], [])}, {})

    def test_filters(self):
        s = check_setup(setup(
            [("k", "kalbos", {}), ("f", "vienetu_sietas", {"attribute": "name", "op": "eq", "value": "A1; b1"}),
             ("gen", "genealoginis_atstumas", {}), ("a", "apriboti", {}), ("t", "lentele", {})],
            [("k", "kalbos", "gen", "vienetai"), ("k", "kalbos", "f", "ka"), ("gen", "atstumai", "a", "ka"), ("f", "ka", "a", "pagal"),
             ("a", "ka", "t", "vienetai")]))
        r = execute(self.read, [], s, {})
        table = r["fruits"][0]["data"]
        self.assertEqual(sorted(table["keys"]), ["a1", "b1"])


class PartTests(unittest.TestCase):
    def test_contract_by_attribute_averages_pairs(self):
        rows = [{"key": f"f{i}", "name": f"f{i}", "language": l, "_language_key": l} for i, l in enumerate("aabb")]
        d = np.array([[0, 1, 4, 4], [1, 0, 6, 2], [4, 6, 0, 3], [4, 2, 3, 0]], float)
        out = PARTS["sutraukti"].fn(None, {"matrica": Distances(Items("forma", rows), d)}, {"attribute": "language"})["matrica"]
        self.assertEqual(out.items.keys(), ["a", "b"])
        self.assertEqual(out.type, "dist")
        self.assertAlmostEqual(out.m[0, 1], 4.0)
        self.assertEqual(out.m[0, 0], 0.0)

    def test_crosstab_aligns_by_key(self):
        a = Partition(Items("x", [{"key": k} for k in "abcd"]), ["1", "1", "2", "2"])
        b = Partition(Items("x", [{"key": k} for k in "dcba"]), ["y", "y", "x", "x"])
        ctx = core.Ctx(None, [], {}, lambda m: None)
        f = PARTS["kryzmine"].fn(ctx, {"a": a, "b": b}, {})
        self.assertEqual(f["tiles"][0]["v"], "1,00")


if __name__ == "__main__":
    unittest.main()
