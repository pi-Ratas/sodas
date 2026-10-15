"""Vaiva: spectral analysis studies of basket nodes.

Every study is a module with ``STUDY`` (id, human title, what it accepts, parameters) and
``run(read, nodes, params, dataset_paths, progress) -> result``. A run is kept as one JSON file in
``<data dir>/vaiva/``; the browser draws its results with the renderer registered for the study id.

Every run keeps the datasets it used (``sources``, see ``kalba_sodas.sekimas``): what its queries read, the datasets of
its basket and those a study names itself (``STUDY["datasets"]``, e.g. CLTS read from files).
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import sekimas
from . import dirbtuves, sound_clusters, stability, tree_fit

STUDIES = {m.STUDY["id"]: m for m in (sound_clusters, tree_fit, stability, dirbtuves)}
RUN_ID = re.compile(r"^[a-z0-9]{8,32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def study_list() -> list[dict[str, Any]]:
    return [m.STUDY for m in STUDIES.values()]


class Vaiva:
    def __init__(self, root: Path, read, dataset_paths, log=lambda *a: None):
        self.root = root / "vaiva"
        self.root.mkdir(parents=True, exist_ok=True)
        self.read = read
        self.dataset_paths = dataset_paths      # callable → {dataset_id: Path}
        self.log = log
        # datasets that can be cited (names), their versions now ({dataset: {version, date}}); the server gives both
        self.known_datasets = lambda: set(self.dataset_paths())
        self.dataset_versions = lambda: {}
        self.lock = threading.Lock()
        self.running: dict[str, dict[str, Any]] = {}

    def _path(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id):
            raise ValueError("bad run id")
        return self.root / f"{run_id}.json"

    def _finished(self) -> list[dict[str, Any]]:
        out = []
        for path in self.root.glob("*.json"):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def runs(self) -> list[dict[str, Any]]:
        running = list(self.running.values())   # one snapshot: a run just finishing is listed once
        out = [{k: r.get(k) for k in ("id", "study", "title", "name", "status", "started_at", "progress")} for r in running]
        shown = {r["id"] for r in running}
        for r in self._finished():
            if r.get("id") in shown:
                continue
            s = (r.get("result") or {}).get("summary") or {}
            out.append({"id": r.get("id"), "study": r.get("study"), "title": r.get("title"), "name": r.get("name"),
                        "status": r.get("status"), "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
                        "summary": {k: s.get(k) for k in ("forms", "included", "clusters", "languages", "rho", "concepts", "blocks", "fruits", "errors")}, "error": r.get("error")})
        return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if run_id in self.running:
            run = dict(self.running[run_id])
        elif path.exists():
            run = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise LookupError("tyrimas nerastas")
        return run

    def delete(self, run_id: str) -> None:
        path = self._path(run_id)
        if path.exists():
            path.unlink()

    def start(self, study_id: str, nodes: list[dict[str, Any]], params: dict[str, Any], name: str | None = None) -> dict[str, Any]:
        if study_id not in STUDIES:
            raise ValueError(f"nežinomas tyrimas: {study_id}")
        if not nodes and not STUDIES[study_id].STUDY.get("basket_optional"):
            raise ValueError("krepšys tuščias")
        study = STUDIES[study_id].STUDY
        run_id = secrets.token_hex(6)
        label = name or (", ".join(str(n.get("display_name") or n.get("key")) for n in nodes[:3]) + ("…" if len(nodes) > 3 else "")
                         if nodes else "visos kalbos")
        run = {"id": run_id, "study": study_id, "title": study["title"], "name": label, "status": "running",
               "started_at": _now(), "progress": "Pradedama…", "nodes": nodes, "params": params}
        with self.lock:
            self.running[run_id] = run
        threading.Thread(target=self._work, args=(run,), daemon=True).start()
        return {k: run[k] for k in ("id", "status", "name")}

    def _work(self, run: dict[str, Any]) -> None:
        def progress(message: str) -> None:
            run["progress"] = message
        tracker = sekimas.Tracker(self.known_datasets())
        tracker.add(*(sekimas.dataset_of_key(n.get("key"), tracker.known) for n in run["nodes"]))
        tracker.add(*STUDIES[run["study"]].STUDY.get("datasets", ()))
        status = "completed"
        try:
            run["result"] = STUDIES[run["study"]].run(tracker.wrap(self.read), run["nodes"], run["params"], self.dataset_paths(), progress)
        except ValueError as exc:
            status, run["error"] = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 – reported to the page and the log
            status, run["error"] = "failed", f"{type(exc).__name__}: {exc}"
            self.log("error", "vaiva", f"tyrimas {run['id']}: {exc}", traceback.format_exc(limit=6))
        run["finished_at"] = _now()
        run.pop("progress", None)
        try:
            versions = self.dataset_versions() or {}
        except Exception:  # noqa: BLE001 – the use is noted without the versions
            versions = {}
        run["sources"] = sekimas.merge_sources(None, tracker.found, versions, run["finished_at"])
        run["status"] = status      # last: a page asking meanwhile sees a finished run only when all of it is there
        with self.lock:
            self._path(run["id"]).write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
            self.running.pop(run["id"], None)
