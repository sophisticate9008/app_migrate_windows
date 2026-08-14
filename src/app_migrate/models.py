from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstalledApplication:
    name: str
    source_path: Path
    icon_path: Path | None = None
    size_bytes: int | None = None
    install_date: date | None = None
    publisher: str = ""
    version: str = ""
    registry_path: str = ""


@dataclass(frozen=True, slots=True)
class DirectoryStats:
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class MigrationRequest:
    source: Path
    destination_base: Path
    intermediate_directory: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    source: Path
    destination: Path
    stats: DirectoryStats
