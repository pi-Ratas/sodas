import json
import tempfile
import unittest
from pathlib import Path

from kalba_import.cypher import _dedupe_nodes
from kalba_import.model import GraphRow
from kalba_import.planner import build_plan
from kalba_import.preview import preview_dataset
from kalba_import.profiles import Profile, load_profile_for

T = "http://cldf.clld.org/v1.0/terms.rdf#"


def col(name, term=None, **kw):
    c = {"name": name, **kw}
    if term:
        c["propertyUrl"] = T + term
    return c


def profile(dataset_id, semantics=None):
    raw = {"contract": "kalba-neo4j/1.1", "dataset_id": dataset_id, "verified": True,
           "input": {"kind": "cldf", "metadata_glob": "cldf-metadata.json"}, "semantics": semantics or {}}
    return Profile(dataset_id, dataset_id, "test", True, raw["input"], raw["semantics"], ["glottolog", "concepticon"], raw, None)


def write_wordlist(root: Path):
    meta = {"dc:conformsTo": T + "Wordlist", "tables": [
        {"url": "forms.csv", "dc:conformsTo": T + "FormTable", "tableSchema": {"primaryKey": ["ID"], "columns": [
            col("ID", "id"), col("Language_ID", "languageReference"), col("Parameter_ID", "parameterReference"), col("Form", "form")]}},
        {"url": "languages.csv", "dc:conformsTo": T + "LanguageTable", "tableSchema": {"primaryKey": ["ID"], "columns": [
            col("ID", "id"), col("Name", "name"), col("Glottocode", "glottocode")]}},
        {"url": "parameters.csv", "dc:conformsTo": T + "ParameterTable", "tableSchema": {"primaryKey": ["ID"], "columns": [
            col("ID", "id"), col("Name", "name"), col("Concepticon_ID", "concepticonReference")]}},
        {"url": "cognates.csv", "dc:conformsTo": T + "CognateTable", "tableSchema": {"primaryKey": ["ID"], "columns": [
            col("ID", "id"), col("Form_ID", "formReference"), col("Cognateset_ID", "cognatesetReference")]}},
        {"url": "cognatesets.csv", "dc:conformsTo": T + "CognatesetTable", "tableSchema": {"primaryKey": ["ID"], "columns": [
            col("ID", "id"), col("Description", "description"), col("Root_Form"), col("Root_Gloss")]}},
    ]}
    (root / "cldf-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (root / "forms.csv").write_text("ID,Language_ID,Parameter_ID,Form\n46-4-1,46,4,pelenaĩ\n45-4-1,45,4,pepeo\n", encoding="utf-8")
    # two varieties share one glottocode: they must stay two Languoids
    (root / "languages.csv").write_text("ID,Name,Glottocode\n46,Lithuanian,lith1251\n45,Latvian,lith1251\n", encoding="utf-8")
    (root / "parameters.csv").write_text("ID,Name,Concepticon_ID\n4,ash,646\n", encoding="utf-8")
    (root / "cognates.csv").write_text("ID,Form_ID,Cognateset_ID\nc1,46-4-1,9\n", encoding="utf-8")
    (root / "cognatesets.csv").write_text("ID,Description,Root_Form,Root_Gloss\n9,,*pel-,dust\n", encoding="utf-8")


class SemanticMappingTests(unittest.TestCase):
    def test_numeric_ids_never_become_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_wordlist(root)
            plan = build_plan("mini", root, profile("mini"))
            display = {n.key: n.props.get("display_name") for rows in plan.nodes.values() for n in rows}
            self.assertEqual(display["mini:languoid:46"], "Lithuanian")
            self.assertEqual(display["mini:languoid:45"], "Latvian")
            self.assertEqual(display["mini:sense:46-4-1"], "ash")
            self.assertEqual(display["mini:concept:4"], "ash")
            # CognateTable must not overwrite the form caption with the form ID
            self.assertEqual(display["mini:form:46-4-1"], "pelenaĩ")
            self.assertEqual(display["mini:cognateset:9"], "*pel- — dust")
            self.assertEqual(display["mini:protoform:9"], "*pel-")
            for label in ("Languoid", "Concept", "Sense", "CognateSet"):
                for n in plan.nodes[label]:
                    self.assertFalse(n.props["display_name"].isdigit(), n)

    def test_cognate_links_to_form_and_owner_cognateset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_wordlist(root)
            plan = build_plan("mini", root, profile("mini"))
            cog = [r for r in plan.relationships if r.rel_type == "COGNATE_IN"]
            self.assertEqual([(r.start_key, r.end_key) for r in cog], [("mini:form:46-4-1", "mini:cognateset:9")])
            self.assertTrue(any(r.rel_type == "RECONSTRUCTED_FOR" for r in plan.relationships))

    def test_dplace_language_table_is_society(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_wordlist(root)
            plan = build_plan("mini", root, profile("mini", {"language_table_label": "Society"}))
            self.assertIn("mini:society:46", {n.key for n in plan.nodes["Society"]})
            self.assertNotIn("Languoid", plan.nodes)

    def test_concepticon_tsv_creates_authority_concepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "concepticondata"
            (data / "references").mkdir(parents=True)
            (data / "concepticon.tsv").write_text("ID\tGLOSS\tSEMANTICFIELD\tDEFINITION\tONTOLOGICAL_CATEGORY\tREPLACEMENT_ID\n646\tASH\tThe physical world\tresidue\tPerson/Thing\t\n2\tDUST\tThe physical world\tparticles\tPerson/Thing\t\n", encoding="utf-8")
            (data / "conceptrelations.tsv").write_text("SOURCE\tSOURCE_GLOSS\tRELATION\tTARGET\tTARGET_GLOSS\n2\tDUST\tsimilar\t646\tASH\n", encoding="utf-8")
            (data / "conceptlists.tsv").write_text("ID\tAUTHOR\n", encoding="utf-8")
            plan = build_plan("concepticon", root, load_profile_for("concepticon"))
            concepts = {n.key: n.props for n in plan.nodes["Concept"]}
            self.assertEqual(concepts["concepticon:646"]["display_name"], "ASH")
            self.assertEqual(concepts["concepticon:646"]["dataset"], "concepticon")
            rel = [r for r in plan.relationships if r.rel_type == "CONCEPT_RELATION"][0]
            self.assertEqual((rel.start_key, rel.end_key, rel.props["relation"]), ("concepticon:2", "concepticon:646", "similar"))
            records = [n for n in plan.nodes["SourceRecord"] if "concepticon.tsv" in n.key]
            self.assertTrue(all(not n.props["unstable_key"] for n in records))

    def test_dedupe_keeps_owner_values(self):
        rows = [GraphRow("Form", "k", {"key": "k", "display_name": "pelenaĩ", "source_record_key": "r1"}),
                GraphRow("Form", "k", {"key": "k", "display_name": "46-4-1", "source_record_key": "r2"})]
        out = _dedupe_nodes(rows)[0]["props"]
        self.assertEqual(out["display_name"], "pelenaĩ")
        self.assertEqual(out["source_record_keys"], ["r1", "r2"])

    def test_preview_filters_and_reports_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_wordlist(root)
            result = preview_dataset("mini", root, profile("mini"), sample=5, filter_text="lithuanian",
                                     neo4j_datasets={"concepticon"})
            forms = [n["display_name"] for n in result["nodes"] if n["label"] == "Form"]
            self.assertEqual(forms, ["pelenaĩ"])
            deps = {d["authority"]: d for d in result["dependencies"]}
            self.assertEqual(deps["glottolog"]["objects"], {"Languoid": 2})
            self.assertTrue(deps["concepticon"]["in_neo4j"])
            self.assertFalse(deps["glottolog"]["in_neo4j"])
            self.assertFalse([q for q in result["quality"] if q["severity"] != "info"])
            self.assertFalse(any(n.get("missing") for n in result["nodes"]))


if __name__ == "__main__":
    unittest.main()
