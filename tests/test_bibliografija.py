"""Which data did a piece of work use, how to cite it: the datasets a garden or a Vaiva run used (sekimas), their
bibliography (bibliografija), a garden as a file, the workshop's draft."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from kalba_import.ui_server import UIState
from kalba_sodas import bibliografija, sekimas
from kalba_sodas.server import SodasApp, make_app_handler
from kalba_sodas.store import Store
from kalba_sodas.vaiva import dirbtuves
from kalba_sodas.vaiva.dirbtuves import core
from tests.test_dirbtuves import setup
from tests.test_vaiva import TreeFitTests, fake_tree_read


def node(label, key, dataset=None, **props):
    return {"data": {"id": f"{label}|{key}", "label": label, "key": key, "dataset": dataset, "props": props}}


class FakeGraph:
    """Neo4j stand-in for the HTTP tests: two datasets, nothing found."""
    allowed = None
    blocked_with = None

    def scoped(self, allowed, blocked=None):
        if allowed is None and not blocked:
            return self
        FakeGraph.blocked_with = blocked
        return self

    def status(self):
        return {"ok": True, "datasets": ["iecor", "glottolog"]}

    def search(self, q, label=None, skip=0, limit=6):
        return {"q": q, "groups": [], "types": []}

    def read(self, *a, **k):
        return []


class TrackingTests(unittest.TestCase):
    def test_dataset_of_a_key(self):
        self.assertEqual(sekimas.dataset_of_key("iecor:form:10-10-1"), "iecor")
        self.assertEqual(sekimas.dataset_of_key("languoid:aala1237"), "glottolog")
        self.assertEqual(sekimas.dataset_of_key("lkezdb@1"), "lkezdb")
        self.assertIsNone(sekimas.dataset_of_key("curated:123"))               # a relationship drawn in the garden
        self.assertIsNone(sekimas.dataset_of_key("vienas"))
        self.assertIsNone(sekimas.dataset_of_key("abc:1", known={"iecor"}))

    def test_garden_datasets_skip_drawn_relationships_and_more_nodes(self):
        g = {"nodes": [node("Form", "iecor:form:1", "iecor"), node("Languoid", "languoid:lith1251"),
                       {"data": {"id": "more1", "kind": "more"}}],
             "edges": [{"data": {"props": {"dataset": "Papildymai"}}}, {"data": {"props": {"dataset": "wold"}}}]}
        self.assertEqual(sekimas.garden_datasets(g), {"iecor", "glottolog", "wold"})

    def test_a_record_keeps_what_was_used_once(self):
        a = sekimas.merge_sources(None, {"iecor"}, {"iecor": {"version": "v1.1"}}, "2026-01-01T00:00:00+00:00")
        b = sekimas.merge_sources(a, {"glottolog"}, {}, "2026-02-01T00:00:00+00:00")
        c = sekimas.merge_sources(b, {"iecor"}, {"iecor": {"version": "v1.2"}}, "2026-03-01T00:00:00+00:00")
        self.assertEqual(set(c), {"iecor", "glottolog"})                        # glottolog stays though not used again
        self.assertEqual(c["iecor"]["versions"], ["v1.1", "v1.2"])
        self.assertEqual((c["iecor"]["first"][:7], c["iecor"]["last"][:7]), ("2026-01", "2026-03"))
        u = sekimas.union_sources({"iecor": {"first": "2026-05", "last": "2026-06", "versions": ["v1.2"]}}, c, {"bad name!": {}})
        self.assertEqual((u["iecor"]["first"], u["iecor"]["last"]), ("2026-01-01T00:00:00+00:00", "2026-06"))
        self.assertNotIn("bad name!", u)

    def test_the_tracker_reads_queries_parameters_and_answers(self):
        t = sekimas.Tracker({"iecor", "glottolog", "concepticon", "datsemshift", "clts"})

        def read(query, **params):
            if "Sound" in query:
                return []                                                     # found nothing: nothing was used
            return [{"key": "iecor:form:1", "dataset": "iecor", "g": "languoid:x", "ids": ["concepticon:5"]}]
        r = t.wrap(read)
        r("MATCH (c:Concept {dataset: 'datsemshift'}) RETURN c", ds="datsemshift")
        r("MATCH (s:Sound) WHERE s.dataset = 'clts' RETURN s")
        self.assertEqual(t.found, {"iecor", "glottolog", "concepticon", "datsemshift"})
        self.assertIs(t.wrap(r).tracker, t)
        self.assertIs(t.wrap(r).raw, read)                                   # never wrapped twice

    def test_what_is_only_asked_about_or_looks_like_a_name_is_not_a_use(self):
        t = sekimas.Tracker({"iecor", "glottolog", "wold", "phoible", "lkezdb"})

        def read(query, **params):
            if "apimtis" in query:
                return [{"key": "lkezdb:languoid:1"}]
            return [{"form": "wold", "system": "phoible", "note": "wold: an English word", "lang": "iecor:languoid:7"}]
        r = t.wrap(read)
        r(sekimas.SCOPE + " MATCH (l:Languoid) RETURN l.key AS key")         # the languages under a branch
        r("MATCH (f:Form) WHERE f.lang IN $langs RETURN f", langs=["lkezdb:languoid:1", "wold:languoid:2"])
        self.assertEqual(t.found, {"iecor"})

    def test_workshop_blocks_follow_their_own_datasets_also_from_the_cache(self):
        core.clear_cache()
        base = fake_tree_read(TreeFitTests().data())

        def read(query, **params):
            rows = base(query, **params)
            return [{**r, "dataset": "iecor"} if "dataset" in r else r for r in rows]
        s = setup([("k", "kalbos", {}), ("gen", "genealoginis_atstumas", {}), ("t", "lentele", {})],
                  [("k", "kalbos", "gen", "vienetai"), ("gen", "atstumai", "t", "vienetai")])
        for _ in range(2):
            t = sekimas.Tracker({"iecor", "glottolog"})
            r = dirbtuves.run(t.wrap(read), [], {"setup": s}, {})
            self.assertEqual(r["blocks"]["k"]["datasets"], ["glottolog", "iecor"])
            self.assertEqual(t.found, {"glottolog", "iecor"})
        self.assertTrue(r["blocks"]["k"]["cached"])
        self.assertEqual(dirbtuves.PARTS["garsinis_atstumas"].datasets, ("clts",))


class BibliographyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def entries(self, sources, versions=None, folders=None):
        own, trial = bibliografija.sodas_entries([self.root / "CITATION.cff"])
        return own + bibliografija.dataset_entries(sources, versions or {}, folders), trial

    def test_iecor_and_glottolog_with_the_trial_sodas_entry(self):
        src = {"iecor": {"first": "2026-10-01T10:00:00+00:00", "last": "2026-10-09T10:00:00+00:00", "versions": ["v1.2"]},
               "glottolog": {"first": "2026-10-09T10:00:00+00:00", "last": "2026-10-09T10:00:00+00:00", "versions": []}}
        entries, trial = self.entries(src, {"glottolog": {"version": "v5.3", "date": "2026-03-02"}})
        self.assertTrue(trial)
        self.assertEqual([e["key"] for e in entries], ["sodas2026", "glottolog2026_v5.3", "iecor2024_v1.2"])
        bib = bibliografija.render("bibtex", entries)
        self.assertIn("@misc{iecor2024_v1.2,", bib)
        self.assertIn("author = {Heggarty, Paul and Anderson, Cormac and Scarborough, Matthew}", bib)
        self.assertIn("doi = {10.5281/zenodo.596479}", bib)
        self.assertIn("urldate = {2026-10-09}", bib)
        self.assertIn("RUOŠIAMA", bib)
        self.assertIn("doi = {10.5281/zenodo.0000000}", bib)                 # the made-up DOI of the trial entry
        ris = bibliografija.render("ris", entries)
        self.assertEqual(ris.count("TY  - "), 3)
        self.assertEqual(ris.count("ER  -"), 3)
        self.assertIn("TY  - COMP", ris)
        self.assertIn("ET  - v1.2", ris)
        self.assertIn("Y2  - 2026/10/09", ris)
        csl = json.loads(bibliografija.render("csl", entries))
        self.assertEqual([c["type"] for c in csl], ["software", "dataset", "dataset"])
        self.assertEqual(csl[2]["author"][0], {"family": "Heggarty", "given": "Paul"})
        self.assertIn("@dataset{iecor2024_v1.2,", bibliografija.render("biblatex", entries))
        text = bibliografija.render("tekstas", entries)
        self.assertIn("Heggarty, P., Anderson, C., & Scarborough, M. (2024). Indo-European Cognate Relationships database (IE-CoR) "
                      "(Version v1.2) [Data set]. Max Planck Institute for Evolutionary Anthropology. https://iecor.clld.org", text)
        with self.assertRaises(ValueError):
            bibliografija.render("docx", entries)

    def test_editors_articles_and_versions(self):
        entries, _ = self.entries({"wals": {"versions": []}, "dplace": {"versions": []}, "iecor": {"versions": ["v1.1", "v1.2"]}})
        self.assertEqual([e["key"] for e in entries if e.get("dataset") == "iecor"], ["iecor2024_v1.1", "iecor2024_v1.2"])
        self.assertIn("editor = {Dryer, Matthew S. and Haspelmath, Martin}", bibliografija.render("biblatex", entries))
        bib = bibliografija.render("bibtex", entries)
        self.assertIn("@article{dplace2016_v3.2.0,", bib)
        self.assertIn("journal = {PLoS ONE}", bib)
        text = bibliografija.render("tekstas", entries)
        self.assertIn("Dryer, M. S., & Haspelmath, M. (Eds.). (2013).", text)
        self.assertIn("Bibiko, H.-J., ", text)
        # a release newer than the catalogue's takes its own year from this computer
        newer, _ = self.entries({"glottolog": {"versions": ["v5.4"]}}, {"glottolog": {"version": "v5.4", "date": "2027-01-15"}})
        self.assertEqual((newer[1]["year"], newer[1]["key"]), (2027, "glottolog2027_v5.4"))

    def test_citation_cff_replaces_the_trial_entry(self):
        (self.root / "CITATION.cff").write_text(
            "cff-version: 1.2.0\ntitle: SODAS\nversion: 1.0.0\ndate-released: 2027-05-01\ndoi: 10.5281/zenodo.123\n"
            "repository-code: https://github.com/tikra/sodas\nauthors:\n  - family-names: Račkaitis\n    given-names: Jonas\n"
            "preferred-citation:\n  type: article\n  title: SODAS straipsnis\n  journal: Baltistica\n  year: 2027\n"
            "  authors:\n    - family-names: Račkaitis\n      given-names: Jonas\n", encoding="utf-8")
        entries, trial = self.entries({})
        self.assertFalse(trial)
        self.assertEqual([e["key"] for e in entries], ["sodas2027", "sodas2027_straipsnis"])
        bib = bibliografija.render("biblatex", entries)
        self.assertIn("@software{sodas2027,", bib)
        self.assertIn("doi = {10.5281/zenodo.123}", bib)
        self.assertIn("@article{sodas2027_straipsnis,", bib)
        self.assertNotIn("RUOŠIAMA", bib)

    def test_a_dataset_outside_the_catalogue_is_cited_from_its_folder(self):
        folder = self.root / "naujas"
        folder.mkdir()
        (folder / ".zenodo.json").write_text(json.dumps({"creators": [{"name": "Ona Onaitė"}, {"name": "Petraitis, Petras"}]}), encoding="utf-8")
        (folder / "metadata.json").write_text(json.dumps({"title": "Naujas duomenynas", "url": "https://naujas.example", "license": "CC0"}),
                                              encoding="utf-8")
        entries, _ = self.entries({"naujas": {"versions": []}, "nezinomas": {"versions": []}}, folders={"naujas": folder})
        by = {e["dataset"]: e for e in entries}
        self.assertEqual(by["naujas"]["title"], "Naujas duomenynas")
        self.assertEqual(by["naujas"]["authors"], [{"family": "Onaitė", "given": "Ona"}, {"family": "Petraitis", "given": "Petras"}])
        self.assertEqual(by["nezinomas"]["title"], "nezinomas")

    def test_the_version_of_a_dataset_folder(self):
        folder = self.root / "ds"
        folder.mkdir()
        (folder / "metadata.json").write_text(json.dumps({"version": "2.0"}), encoding="utf-8")
        self.assertEqual(sekimas.dataset_version(folder), {"version": "2.0"})
        self.assertEqual(sekimas.dataset_version(self.root / "nera"), {})


class GardenSourcesAndFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.store.dataset_versions = lambda: {"iecor": {"version": "v1.2"}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_save_adds_to_the_gardens_own_record(self):
        self.store.save_garden("aaaa1111", {"name": "Mėnulis", "nodes": [node("Form", "iecor:form:1", "iecor")]})
        self.store.save_garden("aaaa1111", {"name": "Mėnulis", "nodes": [node("Languoid", "languoid:lith1251")]})
        src = self.store.garden("aaaa1111")["sources"]
        self.assertEqual(set(src), {"iecor", "glottolog"})                     # IE-CoR was used, though its node is gone
        self.assertEqual(src["iecor"]["versions"], ["v1.2"])
        self.store.save_garden("bbbb2222", {"name": "Kitas", "nodes": [node("Concept", "concepticon:1", "concepticon")]})
        self.assertEqual(set(self.store.garden("bbbb2222")["sources"]), {"concepticon"})   # each garden its own

    def test_a_garden_file_goes_to_another_garden(self):
        loose = {"data": {"id": "r|3", "source": "Form|iecor:form:1", "target": "Form|nera"}}
        edge = {"data": {"id": "r|2", "source": "Form|iecor:form:1", "target": "Form|iecor:form:2"}}
        self.store.save_garden("aaaa1111", {"name": "Mėnulis", "nodes": [node("Form", "iecor:form:1", "iecor"), node("Form", "iecor:form:2", "iecor")],
                                            "edges": [edge], "basket": ["Form|iecor:form:1"]})
        f = self.store.garden_file("aaaa1111")
        self.assertEqual(f["format"], "sodo-byla/1")
        self.assertEqual([e["data"]["id"] for e in f["garden"]["edges"]], ["r|2"])
        self.assertEqual(set(f["sources"]), {"iecor"})
        f = json.loads(json.dumps(f))
        f["garden"]["edges"].append(loose)
        f["garden"]["nodes"][0]["data"]["avatar"] = "https://kitur.example/sekti.png"
        f["garden"]["nodes"][1]["data"]["avatar"] = "/sodas-img/0123456789abcdef01234567.png"
        f["sources"]["glottolog"] = {"first": "2026-01-01T00:00:00+00:00", "last": "2026-01-01T00:00:00+00:00", "versions": ["v5.3"]}
        r = self.store.import_garden(f)
        g = self.store.garden(r["id"])
        self.assertNotEqual(r["id"], "aaaa1111")
        self.assertEqual((g["name"], len(g["nodes"])), ("Mėnulis", 2))
        self.assertEqual([e["data"]["id"] for e in g["edges"]], ["r|2"])        # an edge to a missing node is dropped
        self.assertEqual(set(g["sources"]), {"iecor", "glottolog"})           # the data it used came along
        self.assertEqual(g["basket"], ["Form|iecor:form:1"])
        self.assertEqual([n["data"].get("avatar") for n in g["nodes"]], [None, "/sodas-img/0123456789abcdef01234567.png"])
        for bad in ({"format": "kita"}, {"format": "sodo-byla/1", "garden": {"nodes": []}}, []):
            with self.assertRaises(ValueError):
                self.store.import_garden(bad)
        with self.assertRaises(LookupError):
            self.store.garden_file("cccc3333")

    def test_the_workshops_draft_waits_for_the_next_visit(self):
        self.assertIsNone(self.store.draft("dirbtuves"))
        self.store.save_draft("dirbtuves", {"blocks": [1]})
        self.assertEqual(Store(Path(self.tmp.name)).draft("dirbtuves")["data"], {"blocks": [1]})
        self.store.save_draft("dirbtuves", None)
        self.assertIsNone(self.store.draft("dirbtuves"))
        with self.assertRaises(ValueError):
            self.store.save_draft("kita", {})
        with self.assertRaises(ValueError):
            self.store.save_draft("dirbtuves", {"x": "a" * 600_000})


class HttpWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "datasets.yaml").write_text("datasets: {}\n", encoding="utf-8")
        self.app = SodasApp(Store(root / "data"), root / "neo4j.yaml", root / "datasets.yaml")
        self.app.graph = FakeGraph()
        importer = UIState(root / "datasets.yaml", root / "work", root / "neo4j.yaml", 100)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_app_handler(importer, self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data, {"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_bibliography_and_garden_file_over_http(self):
        self.call("/api/sodas/gardens/aaaa1111", {"name": "Mėnulis", "nodes": [node("Form", "iecor:form:1", "iecor"),
                                                                               node("Languoid", "languoid:lith1251")]})
        status, b = self.call("/api/bibliografija?sodas=aaaa1111&formatas=ris")
        self.assertEqual(status, 200, b)
        self.assertEqual((b["filename"], b["approximate"]), ("Mėnulis.ris", False))
        self.assertEqual([e["dataset"] for e in b["entries"]], ["sodas", "glottolog", "iecor"])
        self.assertIn("TY  - DATA", b["text"])
        self.assertEqual(self.call("/api/bibliografija?sodas=aaaa1111&formatas=docx")[0], 400)
        self.assertEqual(self.call("/api/bibliografija")[1]["entries"][0]["dataset"], "sodas")   # SODAS alone
        status, f = self.call("/api/sodas/gardens/aaaa1111/byla")
        self.assertEqual(status, 200)
        self.assertIn("tekstas", f["bibliografija"])
        status, r = self.call("/api/sodas/sodo-byla", {"file": f})
        self.assertEqual((status, r["name"], r["nodes"]), (200, "Mėnulis", 2))
        self.assertEqual(self.call(f"/api/bibliografija?sodas={r['id']}")[1]["entries"][1]["dataset"], "glottolog")
        self.assertEqual(self.call("/api/sodas/sodo-byla", {"file": {"format": "x"}})[0], 400)
        self.assertEqual(len(self.call("/api/sodas/gardens")[1]["gardens"]), 2)

    def test_the_workshops_draft_over_http(self):
        self.assertIsNone(self.call("/api/vaiva/juodrastis")[1]["draft"])
        self.assertEqual(self.call("/api/vaiva/juodrastis", {"data": {"blocks": [{"id": "a"}]}})[0], 200)
        self.assertEqual(self.call("/api/vaiva/juodrastis")[1]["draft"]["data"], {"blocks": [{"id": "a"}]})

    def test_a_request_from_another_site_changes_nothing(self):
        status, _ = self.call("/api/sodas/gardens/aaaa1111", {"name": "Svetimas", "nodes": [{}]}, {"Origin": "http://kitur.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.call("/api/sodas/gardens")[1]["gardens"], [])

    def test_a_vaiva_run_keeps_its_own_datasets(self):
        self.app.vaiva.read = fake_tree_read(TreeFitTests().data())
        status, r = self.call("/api/vaiva/run", {"study": "kalbu-medis", "nodes": [{"label": "Concept", "key": "concepticon:1"}],
                                                  "params": {"min_overlap": 5, "permutations": 19}})
        self.assertEqual(status, 200, r)
        for _ in range(200):
            run = self.call(f"/api/vaiva/runs/{r['id']}")[1]
            if run["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(set(run["sources"]), {"glottolog", "iecor", "concepticon"})
        b = self.call(f"/api/bibliografija?tyrimas={r['id']}&formatas=bibtex")[1]
        self.assertEqual((b["what"], b["approximate"]), ("tyrimas", False))
        self.assertIn("@misc{iecor2024", b["text"])


if __name__ == "__main__":
    unittest.main()
