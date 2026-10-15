"""„Apie Sodą“ (the window behind the program's sign): whom to write to and which version runs.

The contacts are read from ``kontaktai.yaml`` – next to datasets.yaml, else next to the program – and read again when
the file changes. Only the known fields are passed on, as plain text; empty ones are left out."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

import yaml

FILE_NAME = "kontaktai.yaml"
FIELDS = ("vardas", "pareigos", "institucija", "el_pastas", "telefonas", "adresas", "tinklalapis", "saugykla", "pastaba")
MAX_LEN = 1000
_lock = threading.Lock()
_cache: dict[Path, tuple[float, dict[str, str]]] = {}
_version: str | None = None


def read_contacts(paths: list[Path]) -> dict[str, str]:
    """The fields of the first readable contacts file among ``paths`` (an unreadable one counts as empty)."""
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        with _lock:
            hit = _cache.get(path)
            if hit and hit[0] == mtime:
                return dict(hit[1])
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            raw = {}
        out = {}
        for k in FIELDS:
            v = raw.get(k) if isinstance(raw, dict) else None
            if isinstance(v, (str, int, float)) and str(v).strip():
                out[k] = str(v).strip()[:MAX_LEN]
        with _lock:
            _cache[path] = (mtime, out)
        return dict(out)
    return {}


def version() -> str:
    """The program's version (pyproject) with the git commit it runs from, when it runs from a git checkout."""
    global _version
    if _version is None:
        root = Path(__file__).resolve().parent.parent
        ver = "0.1.0"
        try:
            for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    ver = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass
        try:
            commit = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                    timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            commit = ""
        _version = f"{ver} ({commit})" if commit else ver
    return _version


def about(paths: list[Path]) -> dict[str, Any]:
    return {"program": "Sodas", "version": version(), "contacts": read_contacts(paths)}
