import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from kalba_import.ui_server import UIState
from kalba_sodas.graph import Graph, check_name, check_pattern
from kalba_sodas.server import SodasApp, make_app_handler
from kalba_sodas.store import DEFAULT_SETTINGS, Store


class StoreTests(unittest.TestCase):
    def test_settings_merge_keeps_defaults_and_user_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            saved = store.save_settings({"theme": {"mode": "sun"}, "limits": {"maxNodes": 50}})
            self.assertEqual(saved["theme"]["mode"], "sun")
            self.assertEqual(saved["theme"]["dark"], DEFAULT_SETTINGS["theme"]["dark"])
            self.assertEqual(Store(Path(tmp)).settings()["limits"], {**DEFAULT_SETTINGS["limits"], "maxNodes": 50})

    def test_light_and_dark_palettes_are_separate_and_old_settings_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"theme": {"mode": "dark", "base": {"h": 1, "s": 2, "l": 3}, "accent": {"h": 4, "s": 5, "l": 6}}}
            (Path(tmp) / "settings.json").write_text(json.dumps(old), encoding="utf-8")
            store = Store(Path(tmp))
            theme = store.settings()["theme"]
            self.assertEqual(theme["light"]["base"], {"h": 1, "s": 2, "l": 3})
            self.assertEqual(theme["dark"]["accent"], {"h": 4, "s": 5, "l": 6})
            self.assertNotIn("base", theme)
            theme["light"]["base"]["h"] = 200
            saved = store.save_settings({"theme": theme})
            self.assertEqual((saved["theme"]["light"]["base"]["h"], saved["theme"]["dark"]["base"]["h"]), (200, 1))

    def test_saved_geo_paths_get_new_default_labels_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"map": {"geoPaths": [{"label": "Form", "pattern": "(n)-[:X]->(t:Languoid)"}]}}
            (Path(tmp) / "settings.json").write_text(json.dumps(old), encoding="utf-8")
            store = Store(Path(tmp))
            paths = store.settings()["map"]["geoPaths"]
            self.assertEqual(paths[0]["pattern"], "(n)-[:X]->(t:Languoid)")
            self.assertEqual({g["label"] for g in paths}, {"Form", "Lexeme", "Sense"})
            saved = store.save_settings({"map": {"geoPaths": [p for p in paths if p["label"] != "Sense"], "geoPathsVersion": 2}})
            self.assertNotIn("Sense", {g["label"] for g in saved["map"]["geoPaths"]})
            self.assertIn(("Form", "(n)-[:USED_IN]->(t:Languoid)"), {(g["label"], g["pattern"]) for g in saved["map"]["geoPaths"]})

    def test_saved_computed_get_new_default_paths_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {"computed": [{"name": "language", "label": "Lexeme", "pattern": "(n)-[:USED_IN]->(t:Languoid)"}]}
            (Path(tmp) / "settings.json").write_text(json.dumps(old), encoding="utf-8")
            store = Store(Path(tmp))
            computed = store.settings()["computed"]
            self.assertEqual([(c["label"], c["pattern"]) for c in computed],
                             [("Lexeme", "(n)-[:USED_IN]->(t:Languoid)"), ("Form", "(n)-[:USED_IN]->(t:Languoid)")])
            saved = store.save_settings({"computed": computed[:1], "computedVersion": 2})
            self.assertEqual(len(saved["computed"]), 1)

    def test_flags_for_every_name_of_a_language_but_not_its_old_stages(self):
        from kalba_sodas.flags import assign_flags
        rows = [{"code": "lith1251", "name": "Lithuanian"}, {"code": "czec1258", "name": "Czech"},
                {"code": "czec1258", "name": "Old Czech"}, {"code": "latv1249", "name": "Latvian"}]
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.save_settings({"valueImages": [{"label": "Languoid", "property": "display_name", "value": "Latvian", "image": "/mano.svg"}]})
            r = assign_flags(store, lambda q, **p: rows, lambda code: svg.replace(b"<rect/>", code.encode()))
            self.assertEqual(sorted(r["added"]), ["Czech", "Lithuanian"])
            rules = {v["value"]: v["image"] for v in store.settings()["valueImages"]}
            self.assertEqual(rules["Latvian"], "/mano.svg")          # the researcher's own picture stays
            self.assertNotIn("Old Czech", rules)
            self.assertNotEqual(rules["Czech"], rules["Lithuanian"])
            self.assertEqual(assign_flags(store, lambda q, **p: rows, lambda code: svg)["added"], [])

    def test_duplicate_rename_delete_gardens(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.save_garden("aaaa1111", {"name": "Tyrimas", "nodes": [{"data": {"id": "x"}}]})
            copy_id = store.duplicate_garden("aaaa1111")["id"]
            self.assertEqual(store.garden(copy_id)["name"], "Tyrimas (kopija)")
            self.assertEqual(store.garden(copy_id)["nodes"], [{"data": {"id": "x"}}])
            store.rename_garden(copy_id, "Kitas")
            store.delete_garden("aaaa1111")
            self.assertEqual([g["name"] for g in store.gardens()], ["Kitas"])

    def test_gardens_are_separate_and_ids_are_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.save_garden("aaaa1111", {"name": "Pirmas", "nodes": [{}]})
            store.save_garden("bbbb2222", {"name": "Antras", "nodes": []})
            self.assertEqual({g["name"] for g in store.gardens()}, {"Pirmas", "Antras"})
            self.assertEqual(store.garden("aaaa1111")["name"], "Pirmas")
            with self.assertRaises(ValueError):
                store.save_garden("../../etc", {})

    def test_images_only_known_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            url = store.save_image("lt.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            self.assertTrue(url.startswith("/sodas-img/") and url.endswith(".svg"))
            self.assertEqual(store.image(url.rsplit("/", 1)[-1])[1], "image/svg+xml")
            for name, data in (("x.html", b"<html>"), ("x.svg", b"not svg"), ("x.png", b"")):
                with self.assertRaises(ValueError):
                    store.save_image(name, data)
            self.assertIsNone(store.image("../settings.json"))

    def test_blank_gardens_are_not_kept_or_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            self.assertFalse(store.save_garden("aaaa1111", {"name": "  ", "nodes": []})["saved"])
            self.assertIsNone(store.garden("aaaa1111"))
            store.save_garden("bbbb2222", {"name": "Tyrimas", "nodes": []})
            store.save_garden("bbbb2222", {"name": "", "nodes": []})  # name erased, still empty -> gone
            self.assertIsNone(store.garden("bbbb2222"))
            (Path(tmp) / "gardens").mkdir(exist_ok=True)
            (Path(tmp) / "gardens" / "cccc3333.json").write_text(json.dumps({"id": "cccc3333", "nodes": []}), encoding="utf-8")
            store.save_garden("dddd4444", {"nodes": [{"data": {"id": "x"}}]})
            self.assertEqual([g["id"] for g in store.gardens()], ["dddd4444"])

    def test_log_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            store.log("error", "test", "pirma")
            store.clear_log()
            self.assertEqual(store.log_entries(), [])
            self.assertEqual(Store(Path(tmp)).log_entries(), [])

    def test_log_is_persisted_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            Store(Path(tmp)).log("error", "test", "pirma")
            store = Store(Path(tmp))
            store.log("warning", "test", "antra")
            self.assertEqual([e["message"] for e in store.log_entries()], ["antra", "pirma"])


class ValidationTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(check_name("Languoid"), "Languoid")
        for bad in ("Form`) DETACH DELETE", "a b", "", None, "1x"):
            with self.assertRaises(ValueError):
                check_name(bad)

    def test_computed_pattern_is_a_path_only(self):
        self.assertTrue(check_pattern("(n)<-[:HAS_FORM]-(:Lexeme)-[:USED_IN]->(t:Languoid)"))
        for bad in ("(n)-->(t) RETURN 1", "(n)--(t); MATCH (x) DETACH DELETE x", "MATCH (n)-->(t)", "(n)-->(q)",
                    "(n)-[:X]->(t) WITH n CALL {}", "(n)-->(t:`Bad Label`)"):
            with self.assertRaises(ValueError, msg=bad):
                check_pattern(bad)


class NameSpanTests(unittest.TestCase):
    runs = [{"name": n, "count": c, "labels": ["Sense"], "dataset": "x"} for n, c in (("a", 3), ("b", 1), ("c", 5), ("d", 2))]

    def test_pages_take_whole_names(self):
        taken, end = Graph._take(self.runs, 0, 2)
        self.assertEqual(([r["name"] for r in taken], end), (["a", "b"], 4))
        taken, end = Graph._take(self.runs, 4, 5)
        self.assertEqual(([r["name"] for r in taken], end), (["c", "d"], 11))
        taken, end = Graph._take(self.runs, 2, 1)   # a name cut by an older page is taken whole
        self.assertEqual(([r["name"] for r in taken], end), (["a"], 3))
        self.assertEqual(Graph._take(self.runs, 11, 3), ([], 11))

    def test_a_big_name_comes_as_one_bundle(self):
        g = Graph(lambda: {}, None)
        runs = [{"name": "skin", "count": 10963, "labels": ["Sense"], "dataset": "asjp"},
                {"name": "x", "count": 2, "labels": ["Sense"], "dataset": "asjp"}]
        fetched = []
        g._fetch = lambda src, t, out, names: fetched.append(names) or ([], [])
        src = {"label": "Concept", "key": "asjp:concept:28"}
        page = g._names_page(src, "DENOTES", False, runs, 0, 50)
        self.assertEqual(fetched, [["x"]])
        bundle, edge = page["nodes"][0], page["edges"][0]
        self.assertEqual((bundle["id"], bundle["count"], page["next"]), ("bundle|Concept|asjp:concept:28|DENOTES|in|skin", 10963, 10965))
        self.assertEqual((edge["source"], edge["target"], edge["props"]["count"]), (bundle["id"], "Concept|asjp:concept:28", 10963))
        self.assertEqual(Graph.source_id({"bundle": bundle["bundle"]}), bundle["id"])
        # the settings may ask for bundles from fewer nodes on
        fetched.clear()
        self.assertEqual(len([n for n in g._names_page(src, "DENOTES", False, runs, 0, 50, bundle_min=2)["nodes"] if n.get("kind")]), 2)

    def test_bundle_cypher_starts_from_its_source_and_checks_names(self):
        g = Graph(lambda: {}, None)
        inner = {"source": {"label": "Concept", "key": "c"}, "type": "DENOTES", "out": False, "name": "skin", "label": "Sense"}
        q, params = g._source({"bundle": {"source": {"bundle": inner}, "type": "HAS_SENSE", "out": False, "name": "kin", "label": "Lexeme"}})
        self.assertTrue(q.startswith("MATCH (s1:`Concept` {key: $k2})") or "MATCH (s1:`Concept`" in q, q)
        self.assertEqual(params, {"k2": "c", "n1": "skin", "n0": "kin"})
        with self.assertRaises(ValueError):
            g._source({"bundle": {**inner, "type": "X`]-() DETACH DELETE"}})
        deep = {"label": "Concept", "key": "c"}
        for _ in range(4):
            deep = {"bundle": {"source": deep, "type": "T", "out": True, "name": "n", "label": "L"}}
        with self.assertRaises(ValueError):
            g._source(deep)

    def test_server_checks_the_shape_of_a_bundle(self):
        from kalba_sodas.server import bundle_source
        ok = bundle_source({"source": {"label": "Concept", "key": "c", "extra": 1}, "type": "DENOTES", "out": 0, "name": "skin", "label": "Sense"})
        self.assertEqual(ok["bundle"]["source"], {"label": "Concept", "key": "c"})
        for bad in (None, {"source": "x"}, {"source": {"label": "Concept"}}):
            with self.assertRaises(ValueError):
                bundle_source(bad)


class FakeGraph:
    def status(self):
        return {"ok": True, "datasets": ["iecor"]}

    def search(self, q, label=None, skip=0, limit=6):
        return {"q": q, "groups": [{"label": "Form", "total": 1, "more": False,
                                    "items": [{"id": "Form|k", "label": "Form", "key": "k", "display_name": q, "dataset": "x"}]}], "types": []}

    def expand(self, label, key, mode, limit, types, source=None, bundle_min=None):
        return {"center": f"{label}|{key}", "nodes": [], "edges": [], "more": [], "limit": limit, "mode": mode}

    def geo(self, defs, refs):
        return {"defs": defs, "refs": refs}

    allowed = None

    def scoped(self, allowed, blocked=None):
        self.scoped_with = allowed
        self.blocked_with = blocked
        return self


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "datasets.yaml").write_text("datasets: {}\n", encoding="utf-8")
        self.app = SodasApp(Store(root / "data"), root / "neo4j.yaml")
        self.app.graph = FakeGraph()
        importer = UIState(root / "datasets.yaml", root / "work", root / "neo4j.yaml", 100)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_app_handler(importer, self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.opener = urllib.request.build_opener()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        with self.opener.open(self.base + path) as r:
            return r.status, r.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with self.opener.open(req) as r:
            return json.loads(r.read())

    def test_downloads_carry_the_whole_bibliography(self):
        bib = json.loads(self.get("/api/bibliografija/visa?ir=glottolog,neesamas")[1])
        self.assertEqual({"tekstas", "bibtex", "ris", "csl"} <= set(bib), True)
        datasets = {e["dataset"] for e in bib["entries"]}
        self.assertIn("glottolog", datasets)              # shown on the page (the map of a merged node): cited too
        self.assertNotIn("neesamas", datasets)            # only known datasets
        self.assertIn("Sodas", bib["tekstas"])
        self.post("/api/sodas/gardens/abcd1234", {"name": "Bandymas", "nodes": [{"data": {"id": "Form|iecor:form:1", "label": "Form",
                  "key": "iecor:form:1", "dataset": "iecor"}, "position": {"x": 0, "y": 0}}], "edges": []})
        f = json.loads(self.get("/api/sodas/gardens/abcd1234/byla")[1])
        self.assertIn("iecor", {e["dataset"] for e in f["bibliografija"]["entries"]})
        self.assertIn("@", f["bibliografija"]["bibtex"])

    def test_about_reads_the_contacts_file_and_serves_the_sign(self):
        root = Path(self.tmp.name)
        self.app.datasets_config = root / "datasets.yaml"
        (root / "kontaktai.yaml").write_text('vardas: "Vardas Pavardė"\nel_pastas: vardas@example.lt\ntelefonas: ""\nkita: x\n', encoding="utf-8")
        about = json.loads(self.get("/api/apie")[1])
        self.assertEqual(about["contacts"], {"vardas": "Vardas Pavardė", "el_pastas": "vardas@example.lt"})   # empty and unknown left out
        self.assertTrue(about["version"])
        sign = self.get("/sodas/ikonos/zenklas.svg")[1]
        self.assertIn(b"SodasPamoka", self.get("/sodas/pamoka.js")[1])   # the lessons, loaded when needed
        self.assertIn(b"var(--logo", sign)
        self.assertEqual(self.get("/favicon.ico")[1], self.get("/sodas/ikonos/zenkliukas.svg")[1])
        self.assertIn(b'rel="icon"', self.get("/")[1])

    def test_one_app_serves_garden_and_importer(self):
        page = self.get("/")[1]
        self.assertIn(b"<title>Sodas</title>", page)
        self.assertNotIn(b"kalba-brand", page)  # the garden name box stands where the brand was
        self.assertIn("Duomenynai".encode(), self.get("/importas")[1])   # → Žemė
        self.assertIn("Duomenynai".encode(), self.get("/importas?embed=1")[1])
        self.assertIn(b"sodas.js", self.get("/nustatymai")[1])
        self.assertIn(b"KalbaTheme", self.get("/sodas/theme.js")[1])
        self.assertEqual(self.get("/cytoscape.min.js")[0], 200)
        self.assertIn(b"Leaflet", self.get("/sodas/leaflet.js")[1])
        self.assertEqual(self.get("/sodas/leaflet.css")[0], 200)

    def test_search_and_expand_respect_per_node_limit(self):
        self.assertEqual(json.loads(self.get("/api/sodas/search?q=mie")[1])["groups"][0]["items"][0]["display_name"], "mie")
        self.app.store.save_settings({"limits": {"maxPerNode": 7}})
        self.assertEqual(self.post("/api/sodas/expand", {"label": "Form", "key": "k", "limit": 500})["limit"], 7)

    def test_two_gardens_in_parallel(self):
        self.post("/api/sodas/gardens/aaaa0001", {"name": "A", "nodes": [{"data": {"id": "x"}}]})
        self.post("/api/sodas/gardens/bbbb0002", {"name": "B", "nodes": []})
        self.assertEqual(json.loads(self.get("/api/sodas/gardens/aaaa0001")[1])["name"], "A")
        self.assertEqual(json.loads(self.get("/api/sodas/gardens/bbbb0002")[1])["name"], "B")

    def test_garden_management_routes(self):
        self.post("/api/sodas/gardens/aaaa0001", {"name": "A", "nodes": []})
        new_id = self.post("/api/sodas/gardens/aaaa0001/duplicate", {})["id"]
        self.post(f"/api/sodas/gardens/{new_id}/rename", {"name": "B"})
        self.post("/api/sodas/gardens/aaaa0001/delete", {})
        names = [g["name"] for g in json.loads(self.get("/api/sodas/gardens")[1])["gardens"]]
        self.assertEqual(names, ["B"])

    def test_geo_uses_the_geo_paths_from_settings(self):
        r = self.post("/api/sodas/geo", {"nodes": [{"label": "Form", "key": "f1"}]})
        self.assertEqual(r["refs"], [{"label": "Form", "key": "f1"}])
        self.assertIn({"label": "Form", "pattern": "(n)<-[:HAS_FORM]-(:Lexeme)-[:USED_IN]->(t:Languoid)"}, r["defs"])
        for d in r["defs"]:
            check_pattern(d["pattern"])  # the default paths pass the same check as computed properties

    def test_client_errors_reach_the_log(self):
        self.post("/api/sodas/log", {"level": "error", "message": "naršyklės klaida"})
        self.assertEqual(json.loads(self.get("/api/sodas/log")[1])[0]["message"], "naršyklės klaida")

    def test_no_accounts_here(self):
        for path in ("/povai", "/api/paskyra/as", "/sodas/admin.js"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.get(path)
            self.assertEqual(e.exception.code, 404)
        self.assertNotIn(b"Prisijungti", self.get("/sodas/bar.js")[1])

    def test_switched_off_datasets_are_left_out(self):
        s = self.post("/api/sodas/settings", {**self.post("/api/sodas/settings/reset", {}), "datasetsOff": ["wold", "iecor"]})
        self.assertEqual(s["datasetsOff"], ["iecor", "wold"])
        self.get("/api/sodas/search?q=x")
        self.assertEqual(self.app.graph.blocked_with, ["iecor", "wold"])
        self.assertEqual(self.post("/api/sodas/settings/reset", {})["datasetsOff"], ["iecor", "wold"])   # reset keeps them off


if __name__ == "__main__":
    unittest.main()


class NodeMapTests(unittest.TestCase):
    """🗺 with a Sense or a CognateSet selected: what is placed on the map, asked from Neo4j in one go."""

    def fake(self, rows_by_kind):
        g = Graph(lambda: {}, None)
        seen = []

        def read(q, **p):
            seen.append((q, p))
            if "count(n)" in q:
                return [{"c": len(rows_by_kind["own"])}]
            if "LIMIT $max" in q:
                return rows_by_kind["own"]
            return rows_by_kind.get("geo", [])
        g.read = read
        return g, seen

    def test_lemmas_of_a_sense_fall_back_to_its_forms_and_take_their_place_over_the_geo_path(self):
        own = [{"key": "l1", "label": "Lexeme", "name": "lietus", "ds": "iecor", "lat": None, "lon": None},
               {"key": "f1", "label": "Form", "name": "esmì", "ds": "lkezdb", "lat": 55.1, "lon": 23.9}]
        g, seen = self.fake({"own": own, "geo": [{"k": "l1", "lat": 57.4, "lon": 25.4, "name": "Latvian"}]})
        r = g.related_map([{"label": "Sense", "key": "s1"}], "lemmas", [{"label": "Lexeme", "pattern": "(n)-[:USED_IN]->(t:Languoid)"}])
        self.assertIn("HAS_SENSE", seen[0][0])
        self.assertIn("NOT EXISTS", seen[0][0])          # forms only for a sense without a lexeme
        self.assertEqual(sorted(p[6] for p in r["points"]), ["Form", "Lexeme"])
        self.assertEqual(r["labels"], ["Form", "Lexeme"])
        lex = next(p for p in r["points"] if p[0] == "l1")
        self.assertEqual(lex[4], "Latvian")

    def test_concept_forms_and_cognate_forms(self):
        g, seen = self.fake({"own": []})
        r = g.related_map([{"label": "Sense", "key": "s1"}], "concept_forms", [])
        self.assertIn("DENOTES", seen[0][0])
        self.assertIn("CORRESPONDS_TO", seen[0][0])
        self.assertEqual(r["points"], [])
        g, seen = self.fake({"own": []})
        g.related_map([{"label": "CognateSet", "key": "c1"}], "cognate_forms", [])
        self.assertIn("COGNATE_IN", seen[0][0])
        g, seen = self.fake({"own": []})
        g.related_map([{"label": "Concept", "key": "c1"}], "concept_lemmas", [])
        self.assertIn("CORRESPONDS_TO", seen[0][0])
        self.assertIn("(n:Lexeme)", seen[0][0])
        self.assertNotIn("HAS_FORM", seen[0][0])          # lemmas, not every form

    def test_unknown_way_and_mixed_labels_are_refused(self):
        g, _ = self.fake({"own": []})
        with self.assertRaises(ValueError):
            g.related_map([{"label": "Sense", "key": "s1"}], "x", [])
        with self.assertRaises(ValueError):
            g.related_map([{"label": "Sense", "key": "s1"}, {"label": "Form", "key": "f"}], "lemmas", [])


class DrawnRelationshipTests(unittest.TestCase):
    """Ctrl+J: a relationship goes to Neo4j at once; the program keeps the list (⚙ → Mano ryšiai)."""

    class Graph:
        def __init__(self):
            self.created, self.deleted = [], []

        def schema(self):
            return {"types": ["SIMILAR_TO"]}

        def nodes(self, refs):
            return [{"label": r["label"], "key": r["key"], "display_name": r["key"].upper()} for r in refs]

        def create_relationship(self, a, b, rel_type, note, key=None, extra=None):
            self.created.append((a["key"], b["key"], rel_type, key, extra))
            return {"id": f"r|{key}", "type": rel_type, "props": {"key": key, "dataset": "Papildymai", **(extra or {})}}

        def curated_relationship(self, key, end=None):
            return {"key": key} if key == "curated:senas" else None

        def delete_relationship(self, key, end=None):
            self.deleted.append((key, end))
            return 1

    def test_create_list_and_delete(self):
        from kalba_sodas.rysiai import Relationships
        with tempfile.TemporaryDirectory() as tmp:
            g = self.Graph()
            rels = Relationships(Path(tmp), g)
            a, b = {"label": "Form", "key": "a"}, {"label": "Form", "key": "b"}
            rels.create(a, b, "similar_to", "panašūs")
            e = rels.create(b, a, "mano ryšys", None)
            self.assertEqual([c[2] for c in g.created], ["SIMILAR_TO", "CUSTOM"])   # a known type as it is, else CUSTOM
            self.assertEqual(e["props"]["label"], "mano ryšys")
            listed = Relationships(Path(tmp), g).mine()
            self.assertEqual(len(listed), 2)
            self.assertEqual({r["a"]["name"] for r in listed}, {"A", "B"})
            self.assertEqual(rels.my_labels(), ["mano ryšys"])
            rels.delete("sodas-rysys:1")
            self.assertEqual(g.deleted[-1], ("sodas-rysys:1", {"label": "Form", "key": "a"}))   # found from its node
            self.assertEqual([r["id"] for r in rels.mine()], [2])
            rels.delete("curated:senas", {"label": "Form", "key": "a"})                 # an older one, not on the list
            with self.assertRaises(LookupError):
                rels.delete("curated:nera")
            with self.assertRaises(ValueError):
                rels.create(a, a, "x", None)
            with self.assertRaises(ValueError):
                rels.create(a, b, "  ", None)
