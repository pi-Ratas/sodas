from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .apply import apply_emit
from .cypher import emit
from .inspect import inspect_dataset
from .neo4j_config import neo4j_settings
from .planner import ImportPlan, build_plan, release_key, run_key_for
from .profiles import Profile, load_profile_for
from .util import canonical_json, sha256_text
from .verify import verify_emit
from .stream import emit_large
from .semantics import rule_sha_for
from .neo4j_admin import Neo4jImportState, resolve_neo4j


IMPORT_ORDER = [
    "glottolog",
    "concepticon",
    "clts",
    "iecor",
    "wold",
    "lexibank_analysed",
    "clics4",
    "norare",
    "phoible",
    "wals",
    "grambank",
    "dplace",
    "asjp",
    "datsemshift",
]


@dataclass
class DatasetTask:
    dataset_id: str
    path: Path
    profile: Profile
    plan: ImportPlan | None = None
    blocking_errors: list[str] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_datasets_config(path: Path) -> dict[str, Path]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    datasets = raw.get("datasets", raw)
    if not isinstance(datasets, dict):
        raise ValueError("datasets config must contain a mapping named 'datasets'")
    base = path.parent
    return {str(k): (base / str(v)).resolve() if not Path(str(v)).is_absolute() else Path(str(v)) for k, v in datasets.items()}


def neo4j_settings_from_env(env: dict[str, str] | None = None, config_path: Path | None = None) -> dict[str, str]:
    return neo4j_settings(env=env, config_path=config_path)


def check_neo4j(settings: dict[str, str]) -> dict[str, Any]:
    if not settings.get("password"):
        return {"ok": False, "error": "KALBA_NEO4J_PASSWORD is not set"}
    try:
        from neo4j import GraphDatabase
    except ModuleNotFoundError as exc:
        return {"ok": False, "error": f"official neo4j Python driver is not installed: {exc}"}
    try:
        with GraphDatabase.driver(settings["uri"], auth=(settings["user"], settings["password"])) as driver:
            with driver.session(database=settings["database"]) as session:
                session.run("RETURN 1 AS ok").consume()
        return {"ok": True, "uri": settings["uri"], "database": settings["database"]}
    except Exception as exc:  # pragma: no cover - depends on local server
        return {"ok": False, "error": str(exc), "uri": settings["uri"], "database": settings["database"]}


def _summarize_plan(task: DatasetTask) -> dict[str, Any]:
    plan = task.plan
    if plan is None:
        return {
            "dataset_id": task.dataset_id,
            "path": str(task.path),
            "profile_verified": task.profile.verified,
            "errors": task.blocking_errors or [],
        }
    return {
        "dataset_id": task.dataset_id,
        "path": str(task.path),
        "profile_verified": task.profile.verified,
        "release_key": plan.release_key,
        "config_sha256": plan.config_sha256,
        "rule_sha256": plan.rule_sha256,
        "tables": len(plan.inspect.tables),
        "source_records": len(plan.nodes.get("SourceRecord", [])),
        "assertions": plan.assertions,
        "pending_references": len(plan.nodes.get("RawReference", [])),
        "diagnostics": [d.__dict__ for d in plan.diagnostics],
        "errors": task.blocking_errors or [],
    }


def _preflight_item(dataset_id: str, dataset_path: Path, profile: Profile) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    ins = inspect_dataset(dataset_id, dataset_path, profile)
    hard = [d for d in ins.diagnostics if d.severity == "error"]
    errors.extend(f"{d.code}: {d.message}" for d in hard)
    rkey, manifest_sha = release_key(dataset_id, ins.manifest)
    rule_sha = rule_sha_for(dataset_id, profile)
    item = {
        "dataset_id": dataset_id,
        "path": str(dataset_path),
        "profile_verified": profile.verified,
        "release_key": rkey,
        "manifest_sha256": manifest_sha,
        "config_sha256": profile.config_sha256,
        "rule_sha256": rule_sha,
        "tables": len(ins.tables),
        "table_rows": {str(t.path.relative_to(dataset_path)): t.row_count for t in ins.tables if t.path.is_relative_to(dataset_path)},
        "input_manifest": [m.__dict__ for m in ins.manifest],
        "source_records": sum(t.row_count for t in ins.tables),
        "assertions": None,
        "pending_references": None,
        "diagnostics": [d.__dict__ for d in ins.diagnostics],
        "errors": errors,
    }
    return item, errors


def preflight(
    config_path: Path,
    *,
    db_check: Callable[[dict[str, str]], dict[str, Any]] = check_neo4j,
    env: dict[str, str] | None = None,
    neo4j_config: Path | None = None,
    require_db: bool = True,
    only: list[str] | None = None,
) -> dict[str, Any]:
    paths = read_datasets_config(config_path)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    order = selected_order(only)
    for dataset_id in order:
        profile = load_profile_for(dataset_id)
        dataset_path = paths.get(dataset_id)
        task_errors: list[str] = []
        if dataset_path is None:
            task_errors.append(f"missing path for {dataset_id} in {config_path}")
            dataset_path = Path("")
        elif not dataset_path.exists():
            task_errors.append(f"path does not exist: {dataset_path}")
        if not profile.verified:
            task_errors.append(f"profile is not verified: {profile.source_path}")
        if task_errors:
            item = {
                "dataset_id": dataset_id,
                "path": str(dataset_path),
                "profile_verified": profile.verified,
                "errors": task_errors,
            }
        else:
            item, discovered = _preflight_item(dataset_id, dataset_path, profile)
            task_errors.extend(discovered)
        errors.extend(f"{dataset_id}: {err}" for err in task_errors)
        items.append(item)
    settings = neo4j_settings_from_env(env, neo4j_config)
    db = db_check(settings) if require_db else {"ok": True, "skipped": True}
    if not db.get("ok"):
        errors.append(f"neo4j: {db.get('error', 'not reachable')}")
    summary = {
        "status": "ok" if not errors else "blocked",
        "order": order,
        "neo4j": {"ok": db.get("ok"), "uri": settings["uri"], "database": settings["database"], "error": db.get("error")},
        "datasets": items,
        "errors": errors,
    }
    return summary


def input_fingerprint(root: Path) -> str:
    """Cheap change detector: relative path, size and mtime of every file (no content reads; ~1 s for Glottolog)."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            h.update(f"{os.path.relpath(full, root)}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
    return h.hexdigest()


def _ndjson_edges(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        lines = [ln for ln in fh if ln.strip()]
    return [json.loads(lines[0]), json.loads(lines[-1])] if lines else []


def spot_check(state: Any, emit_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Check first/last row of the first, middle and last applied batch.

    ``apply`` commits batches strictly in manifest order, so if the last row of the last batch exists,
    every earlier batch was committed too; the other probes guard against a manifest that does not match the DB.
    """
    batches = manifest.get("batches", [])
    if not batches:
        return [{"batch": None, "ok": False}]
    picks = sorted({0, len(batches) // 2, len(batches) - 1})
    out = []
    for i in picks:
        batch = batches[i]
        for row in _ndjson_edges(emit_dir / batch["params"]):
            out.append({"batch": batch["params"], "ok": bool(state.row_exists(batch, row))})
    return out


def already_imported(state: Any, dataset_id: str, path: Path, profile: Profile, work_dir: Path,
                     fingerprint: str | None = None) -> dict[str, Any] | None:
    """Return why ``dataset_id`` needs no import, or None. Never reads file contents."""
    runs = state.runs(dataset_id)
    if not runs:
        return None
    fingerprint = fingerprint or input_fingerprint(path)
    current_rule = rule_sha_for(dataset_id, profile)
    for run in runs:
        if run.get("config_sha256") != profile.config_sha256 or run.get("rule_sha256") not in (None, current_rule):
            continue
        if run.get("status") == "completed":
            if run.get("input_fingerprint") == fingerprint:
                return {"reason": "ImportRun būsena completed, profilis ir failai nepakitę", "release_key": run["release_key"],
                        "run_key": run["run_key"]}
            continue
        manifest_path = work_dir / dataset_id / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("release_key") != run["release_key"]:
            continue
        checks = spot_check(state, work_dir / dataset_id, manifest)
        if checks and all(c["ok"] for c in checks):
            state.mark_completed(run["run_key"], fingerprint, utc_now())
            return {"reason": f"{len(checks)} kontroliniai įrašai rasti Neo4j (įskaitant paskutinę partiją); ImportRun pažymėtas completed",
                    "release_key": run["release_key"], "run_key": run["run_key"], "checks": checks}
    return None


def selected_order(only: list[str] | None) -> list[str]:
    if not only:
        return list(IMPORT_ORDER)
    unknown = sorted(set(only) - set(IMPORT_ORDER))
    if unknown:
        raise ValueError(f"unknown dataset(s): {', '.join(unknown)}; known: {', '.join(IMPORT_ORDER)}")
    return [d for d in IMPORT_ORDER if d in set(only)]


def _log_path(work_dir: Path) -> Path:
    return work_dir / "import-all-log.json"


def _load_log(work_dir: Path) -> dict[str, Any] | None:
    path = _log_path(work_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_log(work_dir: Path, log: dict[str, Any]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    _log_path(work_dir).write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _plan_fingerprint(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_key": item.get("release_key"),
        "config_sha256": item.get("config_sha256"),
        "rule_sha256": item.get("rule_sha256"),
    }


def run_import_all(
    config_path: Path,
    work_dir: Path,
    *,
    dry_run: bool = False,
    resume: bool = False,
    batch_size: int = 1000,
    db_check: Callable[[dict[str, str]], dict[str, Any]] = check_neo4j,
    apply_func: Callable[[Path, str, str, str, str], dict[str, Any]] = apply_emit,
    env: dict[str, str] | None = None,
    neo4j_config: Path | None = None,
    progress: Callable[[str], None] | None = None,
    only: list[str] | None = None,
    resolve_func: Callable[..., dict[str, Any]] = resolve_neo4j,
    force: bool = False,
    import_state: Any = None,
) -> dict[str, Any]:
    progress = progress or (lambda message: None)
    settings = neo4j_settings_from_env(env, neo4j_config)
    order = selected_order(only)
    state = import_state
    skipped: dict[str, dict[str, Any]] = {}
    fingerprints: dict[str, str] = {}
    if not dry_run and db_check(settings).get("ok"):
        state = state or Neo4jImportState(settings["uri"], settings["user"], settings["password"], settings["database"])
        paths = read_datasets_config(config_path)
        for dataset_id in order:
            path = paths.get(dataset_id)
            if path is None or not path.exists():
                continue
            progress(f"import-all: {dataset_id}: checking what is already in Neo4j")
            fingerprints[dataset_id] = input_fingerprint(path)
            if force:
                continue
            try:
                reason = already_imported(state, dataset_id, path, load_profile_for(dataset_id), work_dir, fingerprints[dataset_id])
            except Exception as exc:  # a failed check never blocks; it only means "import it"
                progress(f"import-all: {dataset_id}: check failed ({exc}); will import")
                reason = None
            if reason:
                skipped[dataset_id] = reason
                progress(f"import-all: {dataset_id}: already in Neo4j, skipping – {reason['reason']}")
    to_import = [d for d in order if d not in skipped]
    skipped_entries = [{"dataset_id": d, "status": "completed", "skipped": True, "finished_at": utc_now(), **r}
                       for d, r in skipped.items()]
    if not to_import:
        log = {"status": "completed", "started_at": utc_now(), "finished_at": utc_now(), "order": order,
               "datasets": skipped_entries}
        _save_log(work_dir, log)
        progress("import-all: nothing to import")
        return {"status": "completed", "log": log, "preflight": None, "skipped": sorted(skipped)}
    progress("import-all: preflight")
    pre = preflight(config_path, db_check=db_check, env=env, neo4j_config=neo4j_config, require_db=True, only=to_import)
    if dry_run:
        return {"status": pre["status"], "dry_run": True, "preflight": pre}
    if pre["status"] != "ok":
        return {"status": "blocked", "preflight": pre, "skipped": sorted(skipped)}

    previous = _load_log(work_dir) if resume else None
    log = previous or {"status": "running", "started_at": utc_now(), "order": order, "datasets": list(skipped_entries)}
    if resume and previous:
        log["status"] = "running"
        log.pop("failed_dataset", None)
        log.pop("error", None)
        log.pop("finished_at", None)
        _save_log(work_dir, log)
    done = {d["dataset_id"]: d for d in log.get("datasets", []) if d.get("status") == "completed"}

    for item in pre["datasets"]:
        dataset_id = item["dataset_id"]
        progress(f"import-all: {dataset_id}: start")
        if dataset_id in done:
            if _plan_fingerprint(done[dataset_id]) != _plan_fingerprint(item):
                log["status"] = "blocked"
                log["error"] = f"{dataset_id} inputs/profile/rules changed since previous run"
                _save_log(work_dir, log)
                return {"status": "blocked", "log": log, "preflight": pre}
            progress(f"import-all: {dataset_id}: already completed, skipping")
            continue
        prior_entries = [d for d in log.get("datasets", []) if d["dataset_id"] == dataset_id and d.get("status") != "completed"]
        reusable = next(
            (
                d for d in prior_entries
                if _plan_fingerprint(d) == _plan_fingerprint(item)
                and d.get("apply", {}).get("status") == "ok"
            ),
            None,
        )
        if reusable is not None:
            verify = verify_emit(work_dir / dataset_id)
            reusable["verify"] = verify
            reusable["finished_at"] = utc_now()
            reusable["errors"] = verify.get("errors", [])
            if verify["status"] == "ok":
                reusable["status"] = "completed"
                reusable.setdefault("resolve", {"status": "ok", "pending_references": reusable.get("pending_references", 0)})
                _save_log(work_dir, log)
                done[dataset_id] = reusable
                continue
            _save_log(work_dir, log)
        if any(d.get("status") not in {"completed"} for d in log.get("datasets", []) if d["dataset_id"] == dataset_id):
            log["datasets"] = [d for d in log["datasets"] if d["dataset_id"] != dataset_id]

        started = utc_now()
        dataset_dir = work_dir / dataset_id
        profile = load_profile_for(dataset_id)
        progress(f"import-all: {dataset_id}: planning")
        if dataset_id == "clics4" and (item.get("source_records") or 0) >= 1_000_000:
            progress(f"import-all: {dataset_id}: streaming records to disk")
            manifest, stats = emit_large(dataset_id, Path(item["path"]), profile, dataset_dir, batch_size,
                                         known_row_counts=item.get("table_rows"), known_manifest=item.get("input_manifest"))
            plan = None
            plan_errors = [d.__dict__ for d in stats["diagnostics"] if d.severity == "error"]
        else:
            plan = build_plan(dataset_id, Path(item["path"]), profile, strict=True)
            stats = {"release_key": plan.release_key, "config_sha256": plan.config_sha256,
                     "rule_sha256": plan.rule_sha256, "source_records": len(plan.nodes.get("SourceRecord", [])),
                     "assertions": plan.assertions, "pending_references": plan.deferred_references}
            plan_errors = [d.__dict__ for d in plan.diagnostics if d.severity == "error"]
        if plan_errors:
            entry = {
                "dataset_id": dataset_id,
                "status": "failed",
                "release_key": stats["release_key"],
                "config_sha256": stats["config_sha256"],
                "rule_sha256": stats["rule_sha256"],
                "started_at": started,
                "finished_at": utc_now(),
                "source_records": stats["source_records"],
                "assertions": stats["assertions"],
                "pending_references": stats["pending_references"],
                "errors": plan_errors,
                "apply": {"status": "skipped"},
                "verify": {"status": "skipped"},
                "resolve": {"status": "skipped"},
            }
            log.setdefault("datasets", []).append(entry)
            log["status"] = "failed"
            log["failed_dataset"] = dataset_id
            _save_log(work_dir, log)
            return {"status": "failed", "log": log, "preflight": pre}
        progress(f"import-all: {dataset_id}: emitting {stats['source_records']} source records")
        if plan is not None:
            manifest = emit(plan, dataset_dir, batch_size=batch_size)
        progress(f"import-all: {dataset_id}: applying {sum(b['rows'] for b in manifest.get('batches', []))} rows")
        apply_result = apply_func(dataset_dir, settings["uri"], settings["user"], settings["password"], settings["database"])
        progress(f"import-all: {dataset_id}: resolving authority identifiers")
        resolve_report = resolve_func(settings["uri"], settings["user"], settings["password"], settings["database"], progress=progress)
        resolve_report["pending_references"] = sum(b["rows"] for b in manifest.get("batches", []) if b.get("label") == "RawReference")
        progress(f"import-all: {dataset_id}: verifying")
        verify = verify_emit(dataset_dir)
        entry = {
            "dataset_id": dataset_id,
            "status": "completed" if verify["status"] == "ok" else "failed",
            "release_key": stats["release_key"],
            "config_sha256": stats["config_sha256"],
            "rule_sha256": stats["rule_sha256"],
            "started_at": started,
            "finished_at": utc_now(),
            "source_records": stats["source_records"],
            "assertions": stats["assertions"],
            "pending_references": resolve_report["pending_references"],
            "errors": verify.get("errors", []),
            "apply": apply_result,
            "verify": verify,
            "resolve": resolve_report,
        }
        if entry["status"] == "completed" and state is not None:
            state.mark_completed(run_key_for(stats["release_key"], stats["config_sha256"]),
                                 fingerprints.get(dataset_id) or input_fingerprint(Path(item["path"])), entry["finished_at"])
        log.setdefault("datasets", []).append(entry)
        _save_log(work_dir, log)
        if entry["status"] != "completed":
            log["status"] = "failed"
            log["failed_dataset"] = dataset_id
            _save_log(work_dir, log)
            return {"status": "failed", "log": log, "preflight": pre}
        progress(f"import-all: {dataset_id}: completed")

    log["status"] = "completed"
    log["finished_at"] = utc_now()
    log.pop("failed_dataset", None)
    log.pop("error", None)
    _save_log(work_dir, log)
    progress("import-all: completed")
    return {"status": "completed", "log": log, "preflight": pre, "skipped": sorted(skipped)}
