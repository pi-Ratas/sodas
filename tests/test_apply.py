import tempfile
import unittest
from pathlib import Path

from kalba_import.apply import _read_ndjson
from kalba_import.verify import verify_emit


class ApplyTests(unittest.TestCase):
    def test_read_ndjson_preserves_record_separator_inside_json_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.ndjson"
            path.write_text('{"key":"k1","props":{"value":"a\\u001eb"}}\n', encoding="utf-8")
            rows = _read_ndjson(path)
            self.assertEqual(rows, [{"key": "k1", "props": {"value": "a\x1eb"}}])

    def test_verify_counts_physical_ndjson_lines_with_record_separator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                '{"batches":[{"label":"X","rows":1,"cypher":"x.cypher","params":"x.ndjson"}],"diagnostics":[]}',
                encoding="utf-8",
            )
            (root / "x.cypher").write_text("", encoding="utf-8")
            (root / "x.ndjson").write_text('{"key":"k1","props":{"value":"a\\u001eb"}}\n', encoding="utf-8")
            result = verify_emit(root)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["counts"]["rows"], 1)


if __name__ == "__main__":
    unittest.main()
