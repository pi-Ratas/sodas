from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CLDF = "http://cldf.clld.org/v1.0/terms.rdf#"
CONTRACT_VERSION = "kalba-neo4j/1.1"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    property_url: str | None = None
    separator: str | None = None
    null: list[str] = field(default_factory=list)
    datatype: Any = None


@dataclass(frozen=True)
class ForeignKeyInfo:
    columns: tuple[str, ...]
    reference_resource: str
    reference_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableInfo:
    path: Path
    url: str
    role: str
    dialect: dict[str, Any]
    columns: list[ColumnInfo]
    primary_key: tuple[str, ...]
    foreign_keys: list[ForeignKeyInfo]
    row_count: int
    source_metadata: str | None = None
    interpretation: str = "source_records"


@dataclass(frozen=True)
class FileInventory:
    path: str
    status: str
    reason: str


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    sha256: str
    bytes: int


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    record_key: str | None = None
    table: str | None = None
    sample: Any = None


@dataclass
class InspectResult:
    dataset_id: str
    path: Path
    profile_path: Path | None
    status: str
    profile_verified: bool
    metadata_files: list[str]
    tables: list[TableInfo]
    manifest: list[ManifestEntry]
    license_files: list[str]
    citation_files: list[str]
    file_inventory: list[FileInventory] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class GraphRow:
    label: str
    key: str
    props: dict[str, Any]


@dataclass
class RelRow:
    start_label: str
    start_key: str
    rel_type: str
    end_label: str
    end_key: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportPlan:
    inspect: InspectResult
    release_key: str
    manifest_sha256: str
    config_sha256: str
    rule_sha256: str
    nodes: dict[str, list[GraphRow]]
    relationships: list[RelRow]
    diagnostics: list[Diagnostic]
    deferred_references: int = 0
    assertions: int = 0
    identity_candidates: int = 0
