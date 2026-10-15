import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kalba_import.import_all import already_imported, input_fingerprint, run_import_all
from kalba_import.profiles import load_profile_for
from kalba_import.semantics import rule_sha_for


class FakeState:
    def __init__(self, runs, present=None):
        self._runs = runs
        self.present = present  # None = every probed row exists
        self.completed = []
        self.probes = 0

    def runs(self, dataset_id):
        return self._runs

    def row_exists(self, batch, row):
        self.probes += 1
        key = row.get("key") or row["props"]["key"]
        return self.present is None or key in self.present

    def mark_completed(self, run_key, fingerprint, finished_at):
        self.completed.append((run_key, fingerprint))


def setup(tmp: Path):
    data = tmp / "glottolog"
    data.mkdir()
    (data / "a.txt").write_text("x", encoding="utf-8")
    emit_dir = tmp / "work" / "glottolog"
    emit_dir.mkdir(parents=True)
    batches = []
    for i in range(5):
        name = f"node_Languoid_{i:04d}.ndjson"
        (emit_dir / name).write_text("\n".join(json.dumps({"key": f"k{i}-{j}", "props": {}}) for j in range(3)) + "\n", encoding="utf-8")
        batches.append({"kind": "node", "label": "Languoid", "params": name, "rows": 3})
    (emit_dir / "manifest.json").write_text(json.dumps({"release_key": "glottolog@r1", "batches": batches}), encoding="utf-8")
    profile = load_profile_for("glottolog")
    run = {"run_key": "run:1", "release_key": "glottolog@r1", "status": "planned",
           "config_sha256": profile.config_sha256, "rule_sha256": rule_sha_for("glottolog", profile)}
    return data, profile, run


class SkipImportedTests(unittest.TestCase):
    def test_completed_run_with_same_files_is_skipped_without_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, profile, run = setup(Path(tmp))
            run.update(status="completed", input_fingerprint=input_fingerprint(data))
            state = FakeState([run])
            self.assertIsNotNone(already_imported(state, "glottolog", data, profile, Path(tmp) / "work"))
            self.assertEqual(state.probes, 0)

    def test_changed_files_are_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, profile, run = setup(Path(tmp))
            run.update(status="completed", input_fingerprint="old")
            self.assertIsNone(already_imported(FakeState([run]), "glottolog", data, profile, Path(tmp) / "work"))

    def test_unmarked_run_is_confirmed_by_few_spot_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, profile, run = setup(Path(tmp))
            state = FakeState([run])
            reason = already_imported(state, "glottolog", data, profile, Path(tmp) / "work")
            self.assertIsNotNone(reason)
            self.assertEqual(state.probes, 6)  # first/last row of first, middle and last batch
            self.assertEqual(state.completed[0][0], "run:1")

    def test_interrupted_apply_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, profile, run = setup(Path(tmp))
            present = {f"k{i}-{j}" for i in range(4) for j in range(3)}  # last batch never committed
            state = FakeState([run], present)
            self.assertIsNone(already_imported(state, "glottolog", data, profile, Path(tmp) / "work"))
            self.assertEqual(state.completed, [])

    def test_changed_profile_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, profile, run = setup(Path(tmp))
            run.update(status="completed", input_fingerprint=input_fingerprint(data), config_sha256="other")
            self.assertIsNone(already_imported(FakeState([run]), "glottolog", data, profile, Path(tmp) / "work"))

    def test_import_all_skips_without_preflight_or_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, profile, run = setup(Path(tmp))
            run.update(status="completed", input_fingerprint=input_fingerprint(data))
            cfg = Path(tmp) / "datasets.yaml"
            cfg.write_text("datasets:\n  glottolog: glottolog\n", encoding="utf-8")
            with patch("kalba_import.import_all.preflight", side_effect=AssertionError("preflight must not run")):
                result = run_import_all(cfg, Path(tmp) / "work", only=["glottolog"], db_check=lambda s: {"ok": True},
                                        apply_func=lambda *a: (_ for _ in ()).throw(AssertionError("no apply")),
                                        import_state=FakeState([run]), env={"KALBA_NEO4J_PASSWORD": "x"})
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["skipped"], ["glottolog"])


if __name__ == "__main__":
    unittest.main()
