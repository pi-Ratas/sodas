import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from kalba_import.inspect import inspect_dataset
from kalba_import.cypher import emit
from kalba_import.model import TableInfo
from kalba_import.planner import build_plan, record_key
from kalba_import.profiles import load_profile_for
from kalba_import.util import count_rows
from kalba_import.verify import verify_emit
from kalba_import.stream import emit_large


class NewSourceTests(unittest.TestCase):
    def test_glottolog_tree_creates_languoids_and_parent_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "languoids" / "tree" / "fami1234"
            child = parent / "lang1234"
            child.mkdir(parents=True)
            (parent / "md.ini").write_text("[core]\nname = Family\nlevel = family\n", encoding="utf-8")
            (child / "md.ini").write_text("[core]\nname = Language\nlevel = language\n", encoding="utf-8")
            profile = load_profile_for("glottolog")
            plan = build_plan("glottolog", root, profile)
            self.assertFalse([d for d in plan.diagnostics if d.severity == "error"])
            self.assertEqual(len(plan.nodes["SourceRecord"]), 2)
            self.assertEqual({n.key for n in plan.nodes["Languoid"]}, {"languoid:fami1234", "languoid:lang1234"})
            self.assertTrue(any(r.rel_type == "PARENT_OF" and r.start_key == "languoid:fami1234" and r.end_key == "languoid:lang1234" for r in plan.relationships))
            out = root / "output"
            emit(plan, out, batch_size=2)
            self.assertEqual(verify_emit(out)["status"], "ok")

    def test_shared_physical_cldf_table_is_imported_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cldf = root / "cldf"
            cldf.mkdir()
            (cldf / "concepts.csv").write_text("ID,Name\n1,One\n", encoding="utf-8")
            for name, role in (("Wordlist", "ParameterTable"), ("StructureDataset", None)):
                table = {"url": "concepts.csv", "tableSchema": {"columns": [{"name": "ID"}, {"name": "Name"}], "primaryKey": "ID"}}
                if role:
                    table["dc:conformsTo"] = "http://cldf.clld.org/v1.0/terms.rdf#" + role
                (cldf / f"{name}-metadata.json").write_text(json.dumps({"tables": [table]}), encoding="utf-8")
            result = inspect_dataset("clics4", root, load_profile_for("clics4"))
            self.assertEqual(len(result.tables), 1)
            self.assertTrue(result.tables[0].role.endswith("#ParameterTable"))
            self.assertEqual(result.tables[0].row_count, 1)

    def test_clics4_streaming_emit_resolves_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cldf = root / "cldf"
            cldf.mkdir()
            (cldf / "languages.csv").write_text("ID,Name\nl1,Lang\n", encoding="utf-8")
            (cldf / "forms.csv").write_text("ID,Form,Language_ID\n1,foo,l1\n2,bar,l1\n", encoding="utf-8")
            term = "http://cldf.clld.org/v1.0/terms.rdf#"
            tables = [
                {"url": "languages.csv", "dc:conformsTo": term + "LanguageTable", "tableSchema": {
                    "columns": [{"name": "ID", "propertyUrl": term + "id"}, {"name": "Name", "propertyUrl": term + "name"}],
                    "primaryKey": "ID"}},
                {"url": "forms.csv", "dc:conformsTo": term + "FormTable", "tableSchema": {
                    "columns": [{"name": "ID", "propertyUrl": term + "id"}, {"name": "Form", "propertyUrl": term + "form"},
                                {"name": "Language_ID", "propertyUrl": term + "languageReference"}],
                    "primaryKey": "ID", "foreignKeys": [{"columnReference": ["Language_ID"],
                        "reference": {"resource": "languages.csv", "columnReference": ["ID"]}}]}}
            ]
            (cldf / "Wordlist-metadata.json").write_text(json.dumps({"tables": tables}), encoding="utf-8")
            out = root / "out"
            manifest, stats = emit_large("clics4", root, load_profile_for("clics4"), out, batch_size=1)
            self.assertEqual(verify_emit(out)["status"], "ok")
            self.assertEqual(stats["source_records"], 3)
            self.assertEqual(stats["pending_references"], 0)
            self.assertEqual(sum(b["rows"] for b in manifest["batches"] if b.get("type") == "REFERS_TO_RECORD"), 2)
            inspected = inspect_dataset("clics4", root, load_profile_for("clics4"))
            counts = {str(t.path.relative_to(root)): t.row_count for t in inspected.tables}
            with patch("kalba_import.inspect.count_rows", side_effect=AssertionError("recounted")), \
                 patch("kalba_import.inspect.file_manifest", side_effect=AssertionError("rehashed")):
                _, cached_stats = emit_large("clics4", root, load_profile_for("clics4"), root / "cached", 2,
                    known_row_counts=counts, known_manifest=[m.__dict__ for m in inspected.manifest])
            self.assertEqual(cached_stats["source_records"], 3)

    def test_clts_generic_csvw_tables_create_sounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "sources").mkdir()
            (root / "sources" / "index.tsv").write_text("NAME\tDESCRIPTION\tREFS\tTYPE\tURITEMPLATE\nbipa\tB(road) IPA\t\tts\t\n", encoding="utf-8")
            (root / "data" / "features.tsv").write_text(
                "ID\tTYPE\tFEATURE\tVALUE\nconsonant_phonation_voiceless\tconsonant\tphonation\tvoiceless\n"
                "consonant_manner_stop\tconsonant\tmanner\tstop\n", encoding="utf-8")
            (root / "data" / "sounds.tsv").write_text(
                "ID\tNAME\tFEATURES\tTYPE\tGRAPHEME\tUNICODE\tGENERATED\tNOTE\n"
                "voiceless_stop_consonant\tvoiceless stop consonant\tconsonant_phonation_voiceless consonant_manner_stop\tconsonant\tp\tP\t\t\n",
                encoding="utf-8")
            (root / "data" / "graphemes.tsv").write_text(
                "PK\tGRAPHEME\tNAME\tEXPLICIT\tDATASET\tFREQUENCY\tURL\tFEATURES\tIMAGE\tSOUND\tNOTE\n"
                "1\tp\tvoiceless stop consonant\t+\tbipa\t0\t\t\t\t\t\n", encoding="utf-8")
            cols = lambda *names: {"columns": [{"name": n} for n in names]}
            (root / "cldf-metadata.json").write_text(json.dumps({"dialect": {"delimiter": "\t"}, "tables": [
                {"url": "sources/index.tsv", "tableSchema": cols("NAME", "DESCRIPTION", "REFS", "TYPE", "URITEMPLATE")},
                {"url": "data/features.tsv", "tableSchema": cols("ID", "TYPE", "FEATURE", "VALUE")},
                {"url": "data/sounds.tsv", "tableSchema": cols("ID", "NAME", "FEATURES", "TYPE", "GRAPHEME", "UNICODE", "GENERATED", "NOTE")},
                {"url": "data/graphemes.tsv", "tableSchema": cols("PK", "GRAPHEME", "NAME", "EXPLICIT", "DATASET", "FREQUENCY", "URL",
                                                                  "FEATURES", "IMAGE", "SOUND", "NOTE")},
            ]}), encoding="utf-8")
            plan = build_plan("clts", root, load_profile_for("clts"))
            self.assertFalse([d for d in plan.diagnostics if d.severity == "error"])
            sound = plan.nodes["Sound"][0]
            self.assertEqual((sound.key, sound.props["display_name"]), ("clts:sound:voiceless_stop_consonant", "p"))
            self.assertEqual(len(plan.nodes["FeatureValue"]), 2)
            self.assertEqual({n.key for n in plan.nodes["Feature"]}, {"clts:feature:consonant:phonation", "clts:feature:consonant:manner"})
            self.assertEqual(plan.nodes["TranscriptionSystem"][0].key, "clts:system:bipa")
            rels = {(r.rel_type, r.end_key) for r in plan.relationships}
            self.assertIn(("REPRESENTS", sound.key), rels)
            self.assertIn(("IN_SYSTEM", "clts:system:bipa"), rels)
            self.assertIn(("HAS_FEATURE_VALUE", "clts:feature-value:consonant_manner_stop"), rels)

    def test_long_cldf_csv_field_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.csv"
            path.write_text("ID,Notes\n1,\"" + "x" * 200000 + "\"\n", encoding="utf-8")
            self.assertEqual(count_rows(path), 1)

    def test_record_keys_are_scoped_to_physical_table(self):
        a = TableInfo(Path("concepts.csv"), "concepts.csv", "ParameterTable", {}, [], (), [], 1, "cldf/Wordlist-metadata.json")
        b = TableInfo(Path("colexifications.csv"), "colexifications.csv", "ParameterTable", {}, [], (), [], 1, "cldf/StructureDataset-metadata.json")
        self.assertNotEqual(record_key("release", a, 2, {})[0], record_key("release", b, 2, {})[0])

    def test_missing_declared_table_is_blocking_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cldf = root / "cldf"
            cldf.mkdir()
            (cldf / "cldf-metadata.json").write_text(json.dumps({"tables": [{"url": "missing.csv", "tableSchema": {"columns": []}}]}), encoding="utf-8")
            result = inspect_dataset("asjp", root, load_profile_for("asjp"))
            self.assertEqual(result.status, "errors")
            self.assertIn("READ_TABLE_FAILED", {d.code for d in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
