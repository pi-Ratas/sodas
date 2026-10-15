from __future__ import annotations

import importlib.resources as resources
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .model import CONTRACT_VERSION
from .util import canonical_json, sha256_text


@dataclass(frozen=True)
class Profile:
    dataset_id: str
    path_name: str
    profile_version: str
    verified: bool
    input: dict[str, Any]
    semantics: dict[str, Any]
    authorities: list[str]
    raw: dict[str, Any]
    source_path: Path | None = None

    @property
    def config_sha256(self) -> str:
        return sha256_text(canonical_json(self.raw))


def bundled_profile_paths() -> list[Path]:
    root = resources.files("kalba_import").joinpath("profiles")
    return [Path(str(p)) for p in root.iterdir() if p.name.endswith(".yaml")]


def load_profile(path: Path) -> Profile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("contract") != CONTRACT_VERSION:
        raise ValueError(f"{path}: unsupported contract {raw.get('contract')!r}")
    return Profile(
        dataset_id=raw["dataset_id"],
        path_name=raw.get("path_name", raw["dataset_id"]),
        profile_version=str(raw.get("profile_version", "0")),
        verified=bool(raw.get("verified", False)),
        input=raw.get("input", {}),
        semantics=raw.get("semantics", {}),
        authorities=list(raw.get("requires", {}).get("authorities", [])),
        raw=raw,
        source_path=path,
    )


def load_profile_for(dataset: str, explicit: str | None = None) -> Profile:
    if explicit:
        profile = load_profile(Path(explicit))
        if profile.dataset_id != dataset:
            raise ValueError(f"profile dataset_id={profile.dataset_id!r} does not match --dataset {dataset!r}")
        return profile
    for path in bundled_profile_paths():
        profile = load_profile(path)
        if profile.dataset_id == dataset:
            return profile
    known = ", ".join(sorted(load_profile(p).dataset_id for p in bundled_profile_paths()))
    raise ValueError(f"unknown dataset {dataset!r}; known: {known}")
