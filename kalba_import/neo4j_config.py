from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_NEO4J_CONFIG = Path("neo4j.yaml")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def read_neo4j_config(path: Path | None = None) -> dict[str, str]:
    path = path or DEFAULT_NEO4J_CONFIG
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    values = raw.get("neo4j", raw)
    if not isinstance(values, dict):
        raise ValueError(f"{path} must contain a 'neo4j' mapping or top-level settings")
    out: dict[str, str] = {}
    for key in ("uri", "user", "password", "database"):
        value = _clean(values.get(key))
        if value is not None:
            out[key] = value
    return out


def neo4j_settings(
    *,
    config_path: Path | None = None,
    env: dict[str, str] | None = None,
    overrides: dict[str, str | None] | None = None,
) -> dict[str, str]:
    env = env or os.environ
    settings = {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "",
        "database": "neo4j",
    }
    settings.update({k: v for k, v in read_neo4j_config(config_path).items() if v})
    env_values = {
        "uri": _clean(env.get("KALBA_NEO4J_URI")),
        "user": _clean(env.get("KALBA_NEO4J_USER")),
        "password": _clean(env.get("KALBA_NEO4J_PASSWORD")),
        "database": _clean(env.get("KALBA_NEO4J_DATABASE")),
    }
    settings.update({k: v for k, v in env_values.items() if v})
    settings.update({k: v for k, v in (overrides or {}).items() if v})
    return settings
