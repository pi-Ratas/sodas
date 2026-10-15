import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from kalba_import.cypher import emit
from kalba_import.identity import add_identity_candidate
from kalba_import.inspect import inspect_dataset
from kalba_import.planner import build_plan
from kalba_import.profiles import Profile
from kalba_import.verify import verify_emit


def make_profile(root):
    raw = {
        "contract": "kalba-neo4j/1.0",
        "dataset_id": "mini",
        "profile_version": "test",
        "verified": True,
        "input": {"kind": "cldf", "metadata_glob": "cldf-metadata.json", "require_exactly_one_metadata": True},
        "semantics": {},
        "requires": {"authorities": []},
    }
    return Profile("mini", "mini", "test", True, raw["input"], {}, [], raw, None)


def write_fixture(root: Path):
    meta = {
        "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#Wordlist",
        "dc:source": "sources.bib",
        "tables": [
            {
                "url": "languages.csv",
                "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#LanguageTable",
                "tableSchema": {
                    "columns": [
                        {"name": "ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#id"},
                        {"name": "Name", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#name"},
                        {"name": "Glottocode", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#glottocode"},
                    ],
                    "primaryKey": ["ID"],
                },
            },
            {
                "url": "parameters.csv",
                "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#ParameterTable",
                "tableSchema": {
                    "columns": [
                        {"name": "ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#id"},
                        {"name": "Name", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#name"},
                        {"name": "Concepticon_ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#concepticonReference"},
                    ],
                    "primaryKey": ["ID"],
                },
            },
            {
                "url": "forms.csv",
                "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#FormTable",
                "tableSchema": {
                    "columns": [
                        {"name": "ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#id"},
                        {"name": "Language_ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#languageReference"},
                        {"name": "Parameter_ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#parameterReference"},
                        {"name": "Form", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#form", "null": ["NA"]},
                        {"name": "Segments", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#segments", "separator": " "},
                        {"name": "Source", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#source", "separator": ";"},
                    ],
                    "primaryKey": ["ID"],
                    "foreignKeys": [
                        {"columnReference": ["Language_ID"], "reference": {"resource": "languages.csv", "columnReference": ["ID"]}},
                        {"columnReference": ["Parameter_ID"], "reference": {"resource": "parameters.csv", "columnReference": ["ID"]}},
                    ],
                },
            },
            {
                "url": "compound.csv",
                "tableSchema": {
                    "columns": [{"name": "A"}, {"name": "B"}, {"name": "Payload"}],
                    "primaryKey": ["A", "B"],
                },
            },
            {
                "url": "compound_refs.csv",
                "tableSchema": {
                    "columns": [{"name": "ID"}, {"name": "RA", "separator": " "}, {"name": "RB", "separator": " "}],
                    "primaryKey": ["ID"],
                    "foreignKeys": [
                        {"columnReference": ["RA", "RB"], "reference": {"resource": "compound.csv", "columnReference": ["A", "B"]}}
                    ],
                },
            },
        ],
    }
    (root / "cldf-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (root / "sources.bib").write_text("@book{x,title={X}}\n", encoding="utf-8")
    (root / "languages.csv").write_text("ID,Name,Glottocode\nl1,Lang,abcd1234\n", encoding="utf-8")
    (root / "parameters.csv").write_text("ID,Name,Concepticon_ID\np1,water,948\n", encoding="utf-8")
    (root / "forms.csv").write_text("ID,Language_ID,Parameter_ID,Form,Segments,Source\nf1,l1,p1,bank,b a,x;y\nf2,l1,p1,NA,n a,x\n", encoding="utf-8")
    (root / "compound.csv").write_text("A,B,Payload\na1,b1,one\na2,b2,two\n", encoding="utf-8")
    (root / "compound_refs.csv").write_text("ID,RA,RB\nr1,a1 a2,b1 b2\n", encoding="utf-8")
    (root / "unprofiled.tsv").write_text("x\ny\n", encoding="utf-8")


class ImporterTests(unittest.TestCase):
    def test_inspect_reads_cldf_roles_fk_and_bibtex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            result = inspect_dataset("mini", root, make_profile(root))
            self.assertEqual(result.status, "ok")
            self.assertEqual(len(result.tables), 5)
            form_table = [t for t in result.tables if t.url == "forms.csv"][0]
            self.assertEqual(len(form_table.foreign_keys), 2)
            self.assertIn("sources.bib", result.citation_files)
            self.assertTrue(any(f.path == "unprofiled.tsv" and f.status == "not_included" for f in result.file_inventory))

    def test_plan_preserves_rows_and_keeps_homonym_forms_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            plan = build_plan("mini", root, make_profile(root))
            self.assertEqual(len(plan.nodes["SourceRecord"]), 7)
            forms = [n for n in plan.nodes["Form"]]
            self.assertEqual([n.props.get("written") for n in forms], ["bank", None])
            first_form = [n for n in forms if n.props.get("written") == "bank"][0]
            self.assertEqual(first_form.props.get("segments"), ["b", "a"])
            self.assertEqual(plan.deferred_references, 0)
            resolved = [r for r in plan.relationships if r.rel_type == "REFERS_TO_RECORD"]
            self.assertEqual(len(resolved), 6)

    def test_v11_semantic_nodes_and_direct_relationships_are_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            plan = build_plan("mini", root, make_profile(root))
            form = [n for n in plan.nodes["Form"] if n.key == "mini:form:f1"][0]
            self.assertEqual(form.props["display_name"], "bank")
            self.assertEqual(form.props["dataset"], "mini")
            self.assertEqual(form.props["dataset_release"], plan.release_key)
            self.assertEqual(form.props["search_ascii"], "bank")
            rel = [r for r in plan.relationships if r.rel_type == "HAS_FORM"][0]
            self.assertTrue(rel.props["key"].startswith("rel:"))
            self.assertEqual(rel.props["dataset"], "mini")
            self.assertEqual(rel.props["dataset_release"], plan.release_key)
            self.assertEqual(rel.props["rule_id"], "generic-form-has-form-v1")

    def test_references_resolve_to_named_owner_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            plan = build_plan("mini", root, make_profile(root))
            languoids = {n.key: n.props for n in plan.nodes["Languoid"]}
            self.assertEqual(set(languoids), {"mini:languoid:l1"})
            self.assertEqual(languoids["mini:languoid:l1"]["display_name"], "Lang")
            self.assertEqual(languoids["mini:languoid:l1"]["glottocode"], "abcd1234")
            concepts = {n.key: n.props for n in plan.nodes["Concept"]}
            self.assertEqual(set(concepts), {"mini:concept:p1"})
            self.assertEqual(concepts["mini:concept:p1"]["display_name"], "water")
            self.assertEqual({n.props["display_name"] for n in plan.nodes["Sense"]}, {"water"})
            used_in = [r for r in plan.relationships if r.rel_type == "USED_IN"]
            self.assertEqual({r.end_key for r in used_in}, {"mini:languoid:l1"})
            denotes = [r for r in plan.relationships if r.rel_type == "DENOTES"]
            self.assertEqual({r.end_key for r in denotes}, {"mini:concept:p1"})
            # authority objects are referenced only through ExternalIdentifier
            self.assertFalse(any(k.startswith(("languoid:", "concepticon:")) for label in plan.nodes if label != "ExternalIdentifier" for k in (n.key for n in plan.nodes[label])))
            ids = {(r.start_key, r.end_key) for r in plan.relationships if r.rel_type == "IDENTIFIED_BY"}
            self.assertIn(("mini:languoid:l1", "glottolog:glottocode|abcd1234"), ids)
            self.assertIn(("mini:concept:p1", "concepticon:conceptset|948"), ids)

    def test_emit_is_idempotent_and_verify_blocks_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            out = Path(tmp) / "out"
            root.mkdir()
            write_fixture(root)
            plan = build_plan("mini", root, make_profile(root))
            m1 = emit(plan, out, batch_size=2)
            m2 = emit(plan, out, batch_size=2)
            self.assertEqual(m1["release_key"], m2["release_key"])
            result = verify_emit(out)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(any("provenance" in e for e in result["errors"]))

    def test_missing_fk_becomes_diagnostic_and_raw_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            (root / "forms.csv").write_text("ID,Language_ID,Parameter_ID,Form,Segments,Source\nf1,missing,p1,bank,b a,x\n", encoding="utf-8")
            plan = build_plan("mini", root, make_profile(root))
            self.assertTrue(any(d.code == "FK_NOT_FOUND" for d in plan.diagnostics))
            self.assertEqual(len(plan.nodes["RawReference"]), 1)

    def test_external_fk_resource_is_warning_not_internal_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            meta = json.loads((root / "cldf-metadata.json").read_text(encoding="utf-8"))
            meta["tables"][2]["tableSchema"]["foreignKeys"].append(
                {"columnReference": ["Parameter_ID"], "reference": {"resource": "../concepticon.tsv", "columnReference": ["ID"]}}
            )
            (root / "cldf-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
            plan = build_plan("mini", root, make_profile(root))
            self.assertFalse(any(d.severity == "error" and d.code == "FK_TARGET_TABLE_MISSING" for d in plan.diagnostics))
            self.assertTrue(any(d.code == "FK_EXTERNAL_RESOURCE" for d in plan.diagnostics))

    def test_zipped_csv_preserves_record_separator_inside_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            (root / "forms.csv").unlink()
            with zipfile.ZipFile(root / "forms.csv.zip", "w") as zf:
                zf.writestr(
                    "forms.csv",
                    "ID,Language_ID,Parameter_ID,Form,Segments,Source,Value\n"
                    "f1,l1,p1,bank,b a,x,bank\x1e\n",
                )
            plan = build_plan("mini", root, make_profile(root))
            self.assertFalse(any(d.code == "FK_NOT_FOUND" for d in plan.diagnostics))
            form = plan.nodes["Form"][0]
            self.assertEqual(form.props["written"], "bank")

    def test_identity_candidate_can_be_added_to_emit_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            out = Path(tmp) / "out"
            root.mkdir()
            write_fixture(root)
            emit(build_plan("mini", root, make_profile(root)), out, batch_size=10)
            result = add_identity_candidate(
                out,
                "Form",
                "mini:form:f1",
                "Form",
                "mini:form:f2",
                "curated near-match for test",
                "test-candidate-v1",
                evidence={"record_keys": ["r1", "r2"]},
            )
            self.assertTrue(result["candidate_key"].startswith("identity:"))
            verified = verify_emit(out)
            self.assertEqual(verified["status"], "ok")
            possible = json.loads(next((out / p).read_text(encoding="utf-8") for p in out.glob("possible_identity_*.ndjson")).strip())
            self.assertTrue(possible["props"]["key"].startswith("rel:"))


if __name__ == "__main__":
    unittest.main()
