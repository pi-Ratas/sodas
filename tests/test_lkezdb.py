import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kalba_lkezdb import graph_io, plan
from kalba_lkezdb.schema import response_schema
from kalba_lkezdb.store import Store
from kalba_lkezdb.text import article_texts, cross_reference

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).resolve().parents[1]
ARTICLE = "566bbd3d-0ecf-489c-9e37-ee6327d35c88"
HTML = """<fieldset><dl class="word"><dt class="title">Antraštė:</dt><dd class="title">esmi</dd>
<dt class="description">Straipsnelis:</dt><dd class="description">Anksčiau gausios baltų kalbų atematinės veiksmažodžių formos, kaip senosios
lietuvių kalbos <em>esmi</em>, <em>esti</em>, dabartinėse baltų visos pakeistos tematinėmis.</dd>
<dt class="literature">Šaltinis:</dt><dd class="literature"><cite title="Robinson D. F., A note">Robinson 1977</cite>, 226</dd></dl>
<dl class="word"><dt class="title">Antraštė:</dt><dd class="title">esmì</dd><dt class="description">Straipsnelis:</dt>
<dd class="description">žr. <a href="/?w=egl%C4%97">eglė</a></dd></dl></fieldset>"""


def make_db(tmp: Path) -> Path:
    db = tmp / "puslapiai.db"
    c = sqlite3.connect(db)
    c.executescript((ROOT / "kalba_lkezdb" / "puslapiai_schema.sql").read_text(encoding="utf-8"))
    c.execute("INSERT INTO zodziai(GUID, zodis, url, puslapio_GUID, nuskaityta) VALUES('w1', 'esmi', 'https://x/?w=esmi', 'p1', 1)")
    c.execute("INSERT INTO zodziai(GUID, zodis, url, nuskaityta) VALUES('w2', 'eglė', 'https://x/?w=eglė', 1)")
    c.execute("INSERT INTO puslapiai(GUID, LKEZDB_Zodis, LKEZDB_atsakymas) VALUES('p1', 'w1', ?)", (HTML,))
    c.execute("INSERT INTO saltiniai(GUID, santrumpa, saltinis) VALUES('s1', 'Robinson 1977', 'Robinson D. F., A note')")
    c.execute("INSERT INTO saltiniai(GUID, santrumpa, saltinis) VALUES('s2', 'Endzelīns 1971', 'Endzelīns J., Comparative phonology')")
    c.execute("INSERT INTO straipsniai(GUID, LKEZDB_Puslapis, antraste, istrauka, saltinis, metai, vieta_saltinyje) VALUES(?, 'p1', 'esmi', ?, "
              "'Robinson D. F., A note', '1977', '226')",
              (ARTICLE, "Anksčiau gausios baltų kalbų atematinės veiksmažodžių formos, kaip senosios lietuvių kalbosesmi,esti, "
                        "dabartinėse baltų visos pakeistos tematinėmis."))
    c.execute("INSERT INTO straipsniai(GUID, LKEZDB_Puslapis, antraste, istrauka) VALUES('a2', 'p1', 'esmì', 'žr.eglė')")
    c.commit()
    return db


class TextTests(unittest.TestCase):
    def test_italics_and_spaces_come_back_from_html(self):
        t = article_texts(HTML, [{"GUID": "a", "istrauka": "Anksčiau gausios baltų kalbų atematinės veiksmažodžių formos, kaip senosios "
                                  "lietuvių kalbosesmi,esti, dabartinėse baltų visos pakeistos tematinėmis."}])
        self.assertIn("kalbos ⟨esmi⟩, ⟨esti⟩, dabartinėse", t["a"])
        self.assertEqual(cross_reference("žr. eglė"), "eglė")
        self.assertIsNone(cross_reference(t["a"]))


def _validate(schema, value, path="$"):
    """The subset of JSON Schema the answer schema uses."""
    if "anyOf" in schema:
        errors = [e for s in schema["anyOf"] for e in [_validate(s, value, path)]]
        if all(errors):
            return errors[0]
        return None
    types = schema.get("type")
    types = types if isinstance(types, list) else [types]
    pytype = {dict: "object", list: "array", str: "string", bool: "boolean", type(None): "null", int: "integer", float: "number"}[type(value)]
    if pytype not in types:
        return f"{path}: {pytype} not in {types}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: {value!r} not in enum"
    if pytype == "object":
        for k in schema["required"]:
            if k not in value:
                return f"{path}: missing {k}"
        for k, v in value.items():
            if k not in schema["properties"]:
                return f"{path}: extra {k}"
            e = _validate(schema["properties"][k], v, f"{path}.{k}")
            if e:
                return e
    if pytype == "array":
        for i, v in enumerate(value):
            e = _validate(schema["items"], v, f"{path}[{i}]")
            if e:
                return e
    return None


class SchemaTests(unittest.TestCase):
    def test_strict_rules(self):
        def walk(s):
            if s.get("type") == "object" or "properties" in s:
                self.assertFalse(s["additionalProperties"])
                self.assertEqual(sorted(s["required"]), sorted(s["properties"]))
                for v in s["properties"].values():
                    walk(v)
            for v in s.get("anyOf", []):
                walk(v)
            if "items" in s:
                walk(s["items"])
        walk(response_schema())

    def test_sample_answer_fits_schema(self):
        answer = json.loads((DATA / "lkezdb_esmi_atsakymas.json").read_text(encoding="utf-8"))
        self.assertIsNone(_validate(response_schema(), answer))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(make_db(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        w = self.store.word("w1")
        answer = json.loads((DATA / "lkezdb_esmi_atsakymas.json").read_text(encoding="utf-8"))
        analysis, warnings = plan.check(answer, [ARTICLE])
        read = lambda q, **p: [{"code": c, "key": f"languoid:{c}"} for c in p.get("codes", [])] if "codes" in p else \
            [{"gloss": g, "key": "concepticon:1579"} for g in p.get("g", []) if g == "BE"]
        return plan.build(w["word"], w["articles"], analysis, self.store, read, warnings)

    def test_pseudo_lemma_dropped_and_duplicates_merged(self):
        g = self.build()
        w = " ".join(g["warnings"])
        self.assertIn("panašu į gramatinę klasę", w)
        self.assertIn("kartojosi – sujungta", w)
        lexemes = [n["props"]["display_name"] for n in g["nodes"] if n["label"] == "Lexeme"]
        self.assertEqual(lexemes, ["būti"])

    def test_one_feature_link_per_form_and_claims_only_from_article(self):
        g = self.build()
        hfv = [(r["start"], r["end"]) for r in g["relationships"] if r["type"] == "HAS_FEATURE_VALUE"]
        self.assertEqual(len(hfv), len(set(hfv)))
        self.assertEqual(len([s for s, e in hfv if s.endswith(":esmi")]), 1)
        article_out = {r["type"] for r in g["relationships"] if r["start_label"] == "Article"}
        self.assertNotIn("ABOUT", article_out)
        self.assertNotIn("MENTIONS", article_out)          # everything is reached through the claims or the headword
        self.assertIn("HAS_CLAIM", article_out)
        self.assertIn(("Lexeme", "HAS_FORM", "Form"), {(r["start_label"], r["type"], r["end_label"]) for r in g["relationships"]})
        self.assertIn(("Sense", "DENOTES", "Concept"), {(r["start_label"], r["type"], r["end_label"]) for r in g["relationships"]})
        self.assertIn(("Article", "SEE_ALSO", "Entry"), {(r["start_label"], r["type"], r["end_label"]) for r in g["relationships"]})
        cites = [r for r in g["relationships"] if r["type"] == "CITES"]
        self.assertEqual(len(cites), 1)                    # „Endzelīns 1971: 205–208“ found in the source list

    def test_every_node_follows_the_contract(self):
        g = self.build()
        for n in g["nodes"]:
            p = n["props"]
            self.assertTrue(n["key"].startswith("lkezdb"), n["key"])
            self.assertEqual(p["dataset"], "lkezdb")
            self.assertTrue(p["display_name"])
            self.assertTrue(p["source_record_keys"])
            self.assertTrue(p["search_text"])
        for r in g["relationships"]:
            self.assertEqual(r["props"]["dataset"], "lkezdb")
            if r["external"]:
                self.assertIn(r["end_label"], {"Languoid", "Concept"})
        fv = {n["props"]["display_name"] for n in g["nodes"] if n["label"] == "FeatureValue"}
        self.assertEqual(fv, {"atematinė (fleksijos tipas)", "tematinė (fleksijos tipas)"})

    def test_languages_named_like_other_datasets_and_linked_to_glottolog(self):
        g = self.build()
        langs = {n["props"]["name_lt"]: n["props"] for n in g["nodes"] if n["label"] == "Languoid"}
        self.assertEqual(langs["lietuvių"]["display_name"], "Lithuanian")
        self.assertEqual(langs["lietuvių"]["glottocode"], "lith1251")
        words = {n["props"]["language_lt"]: n["props"]["language"] for n in g["nodes"] if n["label"] in ("Form", "Lexeme")}
        self.assertEqual(words, {"lietuvių": "Lithuanian", "senoji lietuvių": "Old Lithuanian"})
        linked = {(r["start"], r["end"]) for r in g["relationships"] if r["type"] == "CORRESPONDS_TO"}
        self.assertIn(("lkezdb:languoid:lietuviu", "languoid:lith1251"), linked)
        self.assertEqual(plan.language_entry("senosios armėnų")[:2], ("clas1249", "Classical Armenian"))
        self.assertEqual(plan.language_entry("Latvian")[:2], ("latv1249", "Latvian"))
        self.assertEqual(plan.language_entry("senoji lietuvių"), ("oldl1240", "Old Lithuanian", "lith1251"))


class GraphIoTests(unittest.TestCase):
    def test_every_write_and_delete_is_limited_to_lkezdb(self):
        seen = []

        class FakeGraph:
            def run(self, q, **p):
                seen.append((q, p))
                return [{"c": 0, "n": 0, "label": "x"}] if "count" in q else []
            write = run

            def driver(self):
                class S:
                    def __enter__(s): return s
                    def __exit__(s, *a): return False
                    def run(s, q, **p):
                        seen.append((q, p))
                        class R:
                            def consume(r): return None
                        return R()

                class D:
                    def session(d, database=None): return S()
                return D(), "neo4j"

        graph_io.remove_records(FakeGraph(), ["lkezdb:record:x"])
        graph_io.delete_all(FakeGraph())
        destructive = [(q, p) for q, p in seen if "DELETE" in q]
        self.assertTrue(destructive)
        for q, p in destructive:
            self.assertIn("n.dataset = $ds", q)
            self.assertIn("n.key STARTS WITH 'lkezdb'", q)   # the key indexes, not every node of 19 labels
            self.assertEqual(p.get("ds"), "lkezdb")
            self.assertNotIn("MATCH (n) ", q)


class StoreTests(unittest.TestCase):
    def test_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(make_db(Path(tmp)))
            job = s.enqueue("w1", True)
            self.assertEqual(s.enqueue("w1", True), job)       # one active job per word
            self.assertEqual(s.claim_job()["GUID"], job)
            s.finish_job(job, "failed", error="be kreditų")
            self.assertEqual(s.jobs()[0]["klaida"], "be kreditų")
            self.assertEqual(s.words("esm")["total"], 1)


if __name__ == "__main__":
    unittest.main()
