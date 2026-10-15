import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from kalba_sodas.vaiva import Vaiva, study_list
from kalba_sodas.vaiva.phonology import SoundInfo, SoundTable, _strip_steps, edit_distance
from kalba_sodas.vaiva.segments import OrthographyProfile, analysis_segments, split_segments
from kalba_sodas.vaiva.spectral import adjusted_rand, spectral_clusters


def profile(tmp: Path) -> OrthographyProfile:
    etc = tmp / "etc"
    etc.mkdir()
    (etc / "orthography.tsv").write_text("Grapheme\tIPA\na\ta\naa\taː\nl\tl\nn\tn\nu\tu\nm\tm\no\to\ne\te\nr\tr\ni\ti\n*\tNULL\n-\t+\n",
                                         encoding="utf-8")
    return OrthographyProfile(etc / "orthography.tsv")


class SegmentTests(unittest.TestCase):
    def test_source_order_segments_then_phonemic_then_orthography(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = profile(Path(tmp))
            self.assertEqual(analysis_segments(["m", "uː", "n"], {"Phonemic_Segments": "x"}, "moon", prof).source, "segments")
            s = analysis_segments(None, {"Phonemic_Segments": "l u n a"}, "luna", prof)
            self.assertEqual((s.source, s.variants), ("phonemic_segments", [["l", "u", "n", "a"]]))
            s = analysis_segments(None, {}, "maan", prof)
            self.assertEqual((s.source, s.variants), ("orthography", [["m", "aː", "n"]]))

    def test_variants_and_missing_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = profile(Path(tmp))
            s = analysis_segments(None, {}, "loir, loer", prof)
            self.assertEqual(s.variants, [["l", "o", "i", "r"], ["l", "o", "e", "r"]])
            s = analysis_segments(None, {}, "menig", prof)
            self.assertEqual(s.reason, "trūksta segmentacijos")
            self.assertIn("„g“", s.detail)
            self.assertEqual(analysis_segments(None, {}, "lune", None).reason, "trūksta segmentacijos")

    def test_reconstructed_forms_are_excluded_unless_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = profile(Path(tmp))
            self.assertEqual(analysis_segments(None, {}, "*arma-", prof).reason, "rekonstruota forma")
            s = analysis_segments(None, {}, "*arma-", prof, include_reconstructed=True)
            self.assertEqual((s.variants, s.reconstructed), ([["a", "r", "m", "a"]], True))

    def test_segment_tokens_are_cleaned(self):
        self.assertEqual(split_segments("ˈl u + n a/ɐ _ ."), ["l", "u", "n", "ɐ"])


class PhonologyTests(unittest.TestCase):
    def test_accents_go_before_length(self):
        self.assertEqual(_strip_steps("òː")[0], "oː")
        self.assertEqual(_strip_steps("a̠ˤ"), ["a̠", "a"])

    def test_feature_distance_and_edit_distance(self):
        t = SoundTable(lambda *a, **k: [])
        t.sounds = {
            "m": SoundInfo("m", "bipa", "m", sound_type="consonant", features={"phonation": "voiced", "place": "bilabial", "manner": "nasal"}),
            "n": SoundInfo("n", "bipa", "n", sound_type="consonant", features={"phonation": "voiced", "place": "alveolar", "manner": "nasal"}),
            "a": SoundInfo("a", "bipa", "a", sound_type="vowel", features={"height": "open"}),
        }
        self.assertAlmostEqual(t.distance("m", "n"), 1 / 3)
        self.assertEqual(t.distance("m", "a"), 1.0)
        self.assertEqual(t.distance("x", "x"), 0.0)
        syms = ["m", "n", "a"]
        sub = [[t.distance(a, b) for b in syms] for a in syms]
        self.assertEqual(edit_distance([0, 2], [0, 2], sub), 0.0)
        self.assertLess(edit_distance([0, 2], [1, 2], sub), edit_distance([0, 2], [2, 2], sub))


class SpectralTests(unittest.TestCase):
    def test_two_obvious_groups(self):
        pts = np.array([[0, 0], [0.1, 0], [0, 0.1], [0.1, 0.1], [5, 5], [5.1, 5], [5, 5.1], [5.1, 5.1]])
        d = np.linalg.norm(pts[:, None] - pts[None], axis=-1)
        sc = spectral_clusters(d)
        self.assertEqual(sc["k"], 2)
        self.assertEqual(len(set(sc["labels"][:4])), 1)
        self.assertNotEqual(sc["labels"][0], sc["labels"][4])
        self.assertAlmostEqual(adjusted_rand(list(sc["labels"]), [0, 0, 0, 0, 1, 1, 1, 1]), 1.0)


class RunTests(unittest.TestCase):
    def test_study_list_and_failed_run_is_kept(self):
        self.assertIn("garsiniai-klasteriai", [s["id"] for s in study_list()])
        with tempfile.TemporaryDirectory() as tmp:
            v = Vaiva(Path(tmp), lambda *a, **k: [], dict)
            run = v.start("garsiniai-klasteriai", [{"label": "Concept", "key": "x"}], {})
            for _ in range(50):
                if v.get(run["id"])["status"] != "running":
                    break
                time.sleep(0.05)
            r = v.get(run["id"])
            self.assertEqual(r["status"], "failed")
            self.assertIn("Krepšyje nėra formų", r["error"])
            self.assertEqual([x["id"] for x in v.runs()], [run["id"]])
            v.delete(run["id"])
            self.assertEqual(v.runs(), [])


if __name__ == "__main__":
    unittest.main()


def fake_tree_read(meanings_per_lang):
    """A read() for tree_fit: two branches A and B under root R; x1 and x2 point to the same Glottolog languoid."""
    paths = {"a1": ["R", "A", "a1"], "a2": ["R", "A", "a2"], "a3": ["R", "A", "a3"], "x1": ["R", "A", "ax"], "x2": ["R", "A", "ax"],
             "b1": ["R", "B", "b1"], "b2": ["R", "B", "b2"], "b3": ["R", "B", "b3"], "c1": ["R", "C", "c1"]}

    def read(query, **params):
        if "COGNATE_IN" in query:
            return [{"lang": lang, "meaning": m, "gloss": m, "cogset": cog} for lang, ms in meanings_per_lang.items() for m, cog in ms.items()]
        if "path_keys" in query:
            return [{"key": k, "name": k.upper(), "dataset": "x", "lat": None, "lon": None, "glottolog": paths[k][-1],
                     "glottolog_name": paths[k][-1], "path_keys": paths[k], "path_names": paths[k]} for k in params["keys"]]
        return []
    return read


class TreeFitTests(unittest.TestCase):
    def data(self):
        m = [f"m{i}" for i in range(10)]
        out = {}
        # m0 is one cognate set in both branches (pairs with nothing in common would not be joined at all)
        for lang in ("a1", "a2", "a3", "x1", "x2"):
            out[lang] = {x: ("Z" if i == 0 else "A" if i < 8 else lang) for i, x in enumerate(m)}
        for lang in ("b1", "b2", "b3"):
            out[lang] = {x: ("Z" if i == 0 else "B" if i < 8 else lang) for i, x in enumerate(m)}
        out["c1"] = {"m0": "C"}   # one meaning only: never reaches the overlap threshold
        return out

    def test_matrices_components_and_findings(self):
        from kalba_sodas.vaiva import tree_fit
        r = tree_fit.run(fake_tree_read(self.data()), [], {"min_overlap": 5, "permutations": 49}, {})
        names = [l["name"] for l in r["languages"]]
        self.assertNotIn("C1", names)
        self.assertEqual([e["reason"] for e in r["excluded"]], ["per mažai bendrų reikšmių"])
        self.assertGreater(r["summary"]["rho"], 0.5)
        self.assertEqual(r["summary"]["clusters"], 2)
        self.assertEqual({b["branch"]: b["monophyletic"] for b in r["branch_fit"]}, {"A": True, "B": True})
        i, j = names.index("X1"), names.index("X2")
        self.assertEqual(r["matrix"]["s"][r["matrix"]["order"].index(i)][r["matrix"]["order"].index(j)], 0.8)
        self.assertIn("rho", [f["id"] for f in r["findings"]])

    def test_same_glottolog_languoid_is_distance_zero(self):
        from kalba_sodas.vaiva import tree_fit
        r = tree_fit.run(fake_tree_read(self.data()), [], {"min_overlap": 5, "permutations": 0, "measure": "edges"}, {})
        zero = [b for b in r["by_distance"] if b["distance"] == 0]
        self.assertEqual(zero[0]["pairs"], 1)   # only x1–x2

    def test_upgma_and_mantel(self):
        from kalba_sodas.vaiva.spectral import mantel, upgma
        d = np.array([[0, 1, 4, 4], [1, 0, 4, 4], [4, 4, 0, 2], [4, 4, 2, 0]], dtype=float)
        tree = upgma(d)
        self.assertEqual(tree[0][:3], [0, 1, 1.0])
        self.assertEqual(tree[-1][2], 4.0)
        rho, p = mantel(d, d, 20)
        self.assertAlmostEqual(rho, 1.0)
        self.assertLessEqual(p, 0.2)


class StabilityTests(unittest.TestCase):
    def test_fitch_counts_fewest_changes(self):
        from kalba_sodas.vaiva.stability import fitch
        paths = {"a1": ["R", "A", "a1"], "a2": ["R", "A", "a2"], "b1": ["R", "B", "b1"], "b2": ["R", "B", "b2"]}
        self.assertEqual(fitch(paths, {"a1": {"x"}, "a2": {"x"}, "b1": {"x"}, "b2": {"x"}}), 0)
        self.assertEqual(fitch(paths, {"a1": {"x"}, "a2": {"x"}, "b1": {"y"}, "b2": {"y"}}), 1)
        self.assertEqual(fitch(paths, {"a1": {"x"}, "a2": {"y"}, "b1": {"z"}, "b2": {"w"}}), 3)
        self.assertEqual(fitch(paths, {"a1": {"x", "y"}, "a2": {"y"}, "b1": {"y"}}), 0)   # polymorphic leaf

    def test_run_keeps_form_and_meaning_apart(self):
        import json as _json
        from kalba_sodas.vaiva import stability
        langs = {f"{b}{i}": ["R", b.upper(), f"{b}{i}"] for b in "abc" for i in range(4)}
        concepts = [str(i) for i in range(8)]
        # concept 0: one class everywhere (stable form); concept 7: a different class in every language
        facts = [{"lang": l, "cid": c, "cogset": ("k" + c if int(c) < 4 else "k" + c + l[0]) if c != "7" else "k7" + l,
                  "cogname": "k" + c, "form": f"w{c}{l}"} for l in langs for c in concepts]

        net = []
        for i in range(12):   # a ring of meanings, every link in several families
            nb = [(i + 1) % 12, (i - 1) % 12]
            net.append({"id": f"s{i}", "cid": str(i) if i < 8 else None, "name": f"m{i}", "raw": _json.dumps({"Linked_Concepts": [
                {"ID": f"s{j}", "Polysemy_Families": ["F1", "F2", "F3"] if j % 2 else ["F1", "F4"], "Derivation_Families": []} for j in nb]})})

        def read(query, **params):
            if "COGNATE_IN" in query:
                return facts
            if "path_keys" in query:
                return [{"key": k, "name": k, "dataset": "x", "lat": None, "lon": None, "glottolog": k, "glottolog_name": k,
                         "path_keys": langs[k], "path_names": langs[k]} for k in params["keys"]]
            if "rec.raw_json" in query:
                return net
            if "semantic_field" in query:
                return [{"cid": c, "name": f"C{c}", "field": "Quantity" if int(c) < 4 else "Motion"} for c in params["ids"]]
            return []

        r = stability.run(read, [], {"min_languages": 5, "min_families": 2, "dims": 2}, {})
        by = {c["cid"]: c for c in r["concepts"]}
        self.assertEqual(r["summary"]["concepts"], 8)
        self.assertEqual(by["0"]["form"]["replacement"], 0)
        self.assertGreater(by["7"]["form"]["replacement"], by["0"]["form"]["replacement"])
        self.assertGreater(by["0"]["pct"]["retention"], by["7"]["pct"]["retention"])
        self.assertIsNotNone(by["0"]["meaning"])
        self.assertIn("twokinds", [f["id"] for f in r["findings"]])
        self.assertIsNone(r["pca"])   # too few concepts for principal components
