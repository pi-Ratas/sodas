from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .apply import apply_emit
from .cypher import emit
from .inspect import inspect_dataset
from .identity import add_identity_candidate
from .import_all import IMPORT_ORDER, run_import_all
from .neo4j_admin import resolve_neo4j
from .neo4j_config import DEFAULT_NEO4J_CONFIG, neo4j_settings
from .planner import build_plan
from .profiles import load_profile_for
from .verify import verify_emit


def _json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _neo4j_settings_from_args(args) -> dict[str, str]:
    settings = neo4j_settings(
        config_path=Path(args.neo4j_config) if args.neo4j_config else DEFAULT_NEO4J_CONFIG,
        overrides={
            "uri": getattr(args, "uri", None),
            "user": getattr(args, "user", None),
            "password": getattr(args, "password", None),
            "database": getattr(args, "database", None),
        },
    )
    if not settings["password"]:
        raise SystemExit(
            "Neo4j password is empty. Put it in neo4j.yaml, export KALBA_NEO4J_PASSWORD, "
            "or pass --password '<slaptažodis>'."
        )
    return settings


def _neo4j_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--neo4j-config", default=str(DEFAULT_NEO4J_CONFIG), help="YAML file with Neo4j uri/user/password/database")
    parser.add_argument("--uri")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("--database")


def _common_dataset_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--strict", action="store_true", default=True)
    parser.add_argument("--lenient", dest="strict", action="store_false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kalba-import")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "plan", "emit"):
        p = sub.add_parser(name)
        _common_dataset_args(p)
        if name == "emit":
            p.add_argument("--out", required=True)
            p.add_argument("--batch-size", type=int, default=1000)
            p.add_argument("--allow-unverified-profile", action="store_true")
    p = sub.add_parser("apply")
    p.add_argument("--emit-dir", required=True)
    _neo4j_args(p)
    p = sub.add_parser("verify")
    p.add_argument("--emit-dir", required=True)
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("resolve", help="link local objects to Glottolog/Concepticon authority objects in Neo4j (idempotent)")
    _neo4j_args(p)
    p = sub.add_parser("candidate-add")
    p.add_argument("--emit-dir", required=True)
    p.add_argument("--left-label", required=True)
    p.add_argument("--left-key", required=True)
    p.add_argument("--right-label", required=True)
    p.add_argument("--right-key", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--rule-id", required=True)
    p.add_argument("--status", default="pending")
    p.add_argument("--evidence-json", default="{}")
    p = sub.add_parser("import-all")
    p.add_argument("--config", required=True, help="datasets.yaml with dataset_id -> local path mapping")
    p.add_argument("--work-dir", default="build/import-all")
    p.add_argument("--batch-size", type=int, default=1000)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--neo4j-config", default=str(DEFAULT_NEO4J_CONFIG), help="YAML file with Neo4j uri/user/password/database")
    p.add_argument("--only", help="comma separated dataset ids; imported in the default order")
    p.add_argument("--force", action="store_true", help="import even if Neo4j already has a completed import of the same files/profile")
    p = sub.add_parser("download", help="download datasets (fixed, tested releases) into the folders datasets.yaml names")
    p.add_argument("--config", default="datasets.yaml", help="datasets.yaml (created with default folders if missing)")
    p.add_argument("--only", help="comma separated dataset ids (default: all that are missing)")
    p.add_argument("--replace", action="store_true", help="download again even if the folder exists")
    p.add_argument("--list", action="store_true", help="only list the datasets, versions, licences and sizes")
    p = sub.add_parser("ui", help="local web app: garden (/) and importer (/importas); same as `sodas`")
    from kalba_sodas.cli import add_serve_args
    add_serve_args(p)
    args = parser.parse_args(argv)

    if args.command == "download":
        from . import download as dl
        config = Path(args.config)
        dl.ensure_config(config)
        if args.list:
            for d in IMPORT_ORDER:
                src = dl.CATALOG[d]
                where = dl.target_for(d, config)
                have = "yra" if where.exists() and any(where.iterdir()) else "nėra"
                print(f"{d:18} {src.version:9} {src.license:13} ~{src.size_mb:>4} MB  {have:4}  {src.page}")
            return 0
        ids = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else list(IMPORT_ORDER)
        result = dl.download_many(ids, config, replace=args.replace)
        return 1 if result["failed"] else 0

    if args.command in {"inspect", "plan", "emit"}:
        profile = load_profile_for(args.dataset, args.profile)
        root = Path(args.path)
        if args.command == "inspect":
            _print_json(inspect_dataset(args.dataset, root, profile))
            return 0
        plan = build_plan(args.dataset, root, profile, strict=args.strict)
        if args.command == "plan":
            summary = {
                "dataset_id": args.dataset,
                "release_key": plan.release_key,
                "tables": len(plan.inspect.tables),
                "source_records": len(plan.nodes.get("SourceRecord", [])),
                "assertions": plan.assertions,
                "deferred_references": plan.deferred_references,
                "identity_candidates": plan.identity_candidates,
                "diagnostics": [d.__dict__ for d in plan.diagnostics],
                "profile_verified": profile.verified,
            }
            _print_json(summary)
            return 1 if args.strict and any(d.severity == "error" for d in plan.diagnostics) else 0
        if not profile.verified and not args.allow_unverified_profile:
            print("Profile is unverified; rerun emit with --allow-unverified-profile after reviewing inspect output.")
            return 2
        manifest = emit(plan, Path(args.out), args.batch_size)
        _print_json({"status": "emitted", "out": args.out, "manifest": manifest})
        return 0
    if args.command == "verify":
        result = verify_emit(Path(args.emit_dir))
        _print_json(result)
        return 1 if args.strict and result["status"] != "ok" else 0
    if args.command == "apply":
        settings = _neo4j_settings_from_args(args)
        result = apply_emit(
            Path(args.emit_dir),
            settings["uri"],
            settings["user"],
            settings["password"],
            settings["database"],
        )
        _print_json(result)
        return 0
    if args.command == "resolve":
        settings = _neo4j_settings_from_args(args)
        _print_json(resolve_neo4j(settings["uri"], settings["user"], settings["password"], settings["database"],
                                  progress=lambda msg: print(msg, file=sys.stderr, flush=True)))
        return 0
    if args.command == "ui":
        from kalba_sodas.cli import serve_from_args
        return serve_from_args(args)
    if args.command == "candidate-add":
        result = add_identity_candidate(
            Path(args.emit_dir),
            args.left_label,
            args.left_key,
            args.right_label,
            args.right_key,
            args.reason,
            args.rule_id,
            args.status,
            json.loads(args.evidence_json),
        )
        _print_json(result)
        return 0
    if args.command == "import-all":
        result = run_import_all(
            Path(args.config),
            Path(args.work_dir),
            dry_run=args.dry_run,
            resume=args.resume,
            batch_size=args.batch_size,
            neo4j_config=Path(args.neo4j_config) if args.neo4j_config else DEFAULT_NEO4J_CONFIG,
            progress=lambda msg: print(msg, file=sys.stderr, flush=True),
            only=[d.strip() for d in args.only.split(",") if d.strip()] if args.only else None,
            force=args.force,
        )
        _print_json(result)
        return 0 if result["status"] in {"ok", "completed"} else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
