import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kalba_import.import_all import IMPORT_ORDER, preflight, run_import_all


class EmptyState:
    """Neo4j without earlier imports."""
    def runs(self, dataset_id):
        return []

    def mark_completed(self, *args):
        pass


def write_config(root: Path) -> Path:
    data = root / "data"
    data.mkdir()
    lines = ["datasets:"]
    for ds in IMPORT_ORDER:
        folder = data / ds
        folder.mkdir()
        lines.append(f"  {ds}: data/{ds}")
    cfg = root / "datasets.yaml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


def fake_plan(dataset_id, path, profile, strict=True):
    return SimpleNamespace(
        release_key=f"{dataset_id}@release",
        config_sha256=f"config-{dataset_id}",
        rule_sha256=f"rule-{dataset_id}",
        inspect=SimpleNamespace(tables=[1]),
        nodes={"SourceRecord": [1, 2], "RawReference": []},
        relationships=[],
        diagnostics=[],
        assertions=3,
        deferred_references=0,
        identity_candidates=0,
    )


def fake_emit(plan, out_dir, batch_size=1000):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps({
        "release_key": plan.release_key,
        "batches": [],
        "diagnostics": [],
    }), encoding="utf-8")
    (out_dir / "constraints.cypher").write_text("", encoding="utf-8")
    return {"release_key": plan.release_key, "batches": [], "diagnostics": []}


def fake_preflight_item(dataset_id, dataset_path, profile):
    return {
        "dataset_id": dataset_id,
        "path": str(dataset_path),
        "profile_verified": True,
        "release_key": f"{dataset_id}@release",
        "config_sha256": f"config-{dataset_id}",
        "rule_sha256": f"rule-{dataset_id}",
        "tables": 1,
        "source_records": 2,
        "assertions": None,
        "pending_references": None,
        "diagnostics": [],
        "errors": [],
    }, []


class ImportAllTests(unittest.TestCase):
    def test_default_order_and_dry_run_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp))
            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item):
                result = preflight(cfg, db_check=lambda settings: {"ok": True})
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["order"], IMPORT_ORDER)
            self.assertEqual([d["dataset_id"] for d in result["datasets"]], IMPORT_ORDER)

    def test_preflight_blocks_when_dataset_path_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp))
            text = cfg.read_text(encoding="utf-8").replace("data/wold", "data/absent-wold")
            cfg.write_text(text, encoding="utf-8")
            result = preflight(cfg, db_check=lambda settings: {"ok": True})
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(any("wold" in e for e in result["errors"]))

    def test_import_stops_after_failed_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp))
            calls = []

            def verify(out_dir):
                dataset_id = out_dir.name
                if dataset_id == "concepticon":
                    return {"status": "error", "errors": ["boom"], "counts": {}}
                return {"status": "ok", "errors": [], "counts": {}}

            def apply(out_dir, uri, user, password, database):
                calls.append(out_dir.name)
                return {"status": "ok", "rows": 0}

            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.build_plan", side_effect=fake_plan), \
                    patch("kalba_import.import_all.emit", side_effect=fake_emit), \
                    patch("kalba_import.import_all.verify_emit", side_effect=verify):
                result = run_import_all(
                    cfg,
                    Path(tmp) / "work",
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=apply,
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(calls, ["glottolog", "concepticon"])
            self.assertEqual(result["log"]["failed_dataset"], "concepticon")

    def test_import_stops_after_failed_plan_before_emit_or_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp))

            def plan(dataset_id, path, profile, strict=True):
                result = fake_plan(dataset_id, path, profile, strict)
                if dataset_id == "glottolog":
                    result.diagnostics = [SimpleNamespace(severity="error", code="BAD_FK", message="broken")]
                    result.deferred_references = 1
                return result

            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.build_plan", side_effect=plan), \
                    patch("kalba_import.import_all.emit", side_effect=AssertionError("should not emit")):
                result = run_import_all(
                    cfg,
                    Path(tmp) / "work",
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=lambda *args: (_ for _ in ()).throw(AssertionError("should not apply")),
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["log"]["failed_dataset"], "glottolog")
            self.assertEqual(result["log"]["datasets"][0]["apply"]["status"], "skipped")

    def test_resume_skips_completed_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = write_config(root)
            work = root / "work"
            work.mkdir()
            (work / "import-all-log.json").write_text(json.dumps({
                "status": "running",
                "started_at": "x",
                "order": IMPORT_ORDER,
                "datasets": [{
                    "dataset_id": "glottolog",
                    "status": "completed",
                    "release_key": "glottolog@release",
                    "config_sha256": "config-glottolog",
                    "rule_sha256": "rule-glottolog",
                }],
            }), encoding="utf-8")
            calls = []

            def apply(out_dir, uri, user, password, database):
                calls.append(out_dir.name)
                return {"status": "ok", "rows": 0}

            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.build_plan", side_effect=fake_plan), \
                    patch("kalba_import.import_all.emit", side_effect=fake_emit), \
                    patch("kalba_import.import_all.verify_emit", return_value={"status": "ok", "errors": [], "counts": {}}):
                result = run_import_all(
                    cfg,
                    work,
                    resume=True,
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=apply,
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(calls[0], "concepticon")
            self.assertNotIn("glottolog", calls)

    def test_resume_clears_stale_failed_status_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = write_config(root)
            work = root / "work"
            work.mkdir()
            (work / "import-all-log.json").write_text(json.dumps({
                "status": "failed",
                "failed_dataset": "concepticon",
                "error": "old failure",
                "started_at": "x",
                "finished_at": "old",
                "order": IMPORT_ORDER,
                "datasets": [{
                    "dataset_id": "glottolog",
                    "status": "completed",
                    "release_key": "glottolog@release",
                    "config_sha256": "config-glottolog",
                    "rule_sha256": "rule-glottolog",
                }],
            }), encoding="utf-8")

            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.build_plan", side_effect=fake_plan), \
                    patch("kalba_import.import_all.emit", side_effect=fake_emit), \
                    patch("kalba_import.import_all.verify_emit", return_value={"status": "ok", "errors": [], "counts": {}}):
                result = run_import_all(
                    cfg,
                    work,
                    resume=True,
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=lambda *args: {"status": "ok", "rows": 0},
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["log"]["status"], "completed")
            self.assertNotIn("failed_dataset", result["log"])
            self.assertNotIn("error", result["log"])

    def test_resume_reuses_applied_dataset_when_verify_now_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = write_config(root)
            work = root / "work"
            work.mkdir()
            (work / "import-all-log.json").write_text(json.dumps({
                "status": "failed",
                "failed_dataset": "glottolog",
                "started_at": "x",
                "order": IMPORT_ORDER,
                "datasets": [{
                    "dataset_id": "glottolog",
                    "status": "failed",
                    "release_key": "glottolog@release",
                    "config_sha256": "config-glottolog",
                    "rule_sha256": "rule-glottolog",
                    "pending_references": 0,
                    "apply": {"status": "ok", "rows": 1},
                    "verify": {"status": "error", "errors": ["old"]},
                    "errors": ["old"],
                }],
            }), encoding="utf-8")

            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.verify_emit", return_value={"status": "ok", "errors": [], "counts": {}}), \
                    patch("kalba_import.import_all.build_plan", side_effect=fake_plan), \
                    patch("kalba_import.import_all.emit", side_effect=fake_emit):
                result = run_import_all(
                    cfg,
                    work,
                    resume=True,
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=lambda *args: {"status": "ok", "rows": 0},
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            first = result["log"]["datasets"][0]
            self.assertEqual(first["dataset_id"], "glottolog")
            self.assertEqual(first["status"], "completed")
            self.assertEqual(first["errors"], [])

    def test_completed_resume_does_not_duplicate_log_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = write_config(root)
            work = root / "work"
            log = {
                "status": "completed",
                "started_at": "x",
                "order": IMPORT_ORDER,
                "datasets": [
                    {
                        "dataset_id": ds,
                        "status": "completed",
                        "release_key": f"{ds}@release",
                        "config_sha256": f"config-{ds}",
                        "rule_sha256": f"rule-{ds}",
                    }
                    for ds in IMPORT_ORDER
                ],
            }
            work.mkdir()
            (work / "import-all-log.json").write_text(json.dumps(log), encoding="utf-8")
            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.build_plan", side_effect=fake_plan), \
                    patch("kalba_import.import_all.emit", side_effect=AssertionError("should not emit")):
                result = run_import_all(
                    cfg,
                    work,
                    resume=True,
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=lambda *args: {"status": "ok"},
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(len(result["log"]["datasets"]), len(IMPORT_ORDER))

    def test_lexibank_iecor_wold_release_provenance_stays_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = write_config(Path(tmp))
            with patch("kalba_import.import_all._preflight_item", side_effect=fake_preflight_item), \
                    patch("kalba_import.import_all.build_plan", side_effect=fake_plan), \
                    patch("kalba_import.import_all.emit", side_effect=fake_emit), \
                    patch("kalba_import.import_all.verify_emit", return_value={"status": "ok", "errors": [], "counts": {}}):
                result = run_import_all(
                    cfg,
                    Path(tmp) / "work",
                    db_check=lambda settings: {"ok": True},
                    import_state=EmptyState(),
                    resolve_func=lambda *a, **k: {"status": "ok"},
                    apply_func=lambda *args: {"status": "ok", "rows": 0},
                    env={"KALBA_NEO4J_PASSWORD": "secret"},
                )
            releases = {d["dataset_id"]: d["release_key"] for d in result["log"]["datasets"]}
            self.assertEqual(len({releases["iecor"], releases["wold"], releases["lexibank_analysed"]}), 3)


if __name__ == "__main__":
    unittest.main()
