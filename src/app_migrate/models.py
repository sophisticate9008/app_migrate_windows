from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApplicationDirectory:
    path: Path
    role: str
    destination_name: str
    size_bytes: int | None = None


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
    storage_name: str = ""
    primary_size_bytes: int | None = None
    related_directories: tuple[ApplicationDirectory, ...] = ()

    @property
    def directories(self) -> tuple[ApplicationDirectory, ...]:
        primary = ApplicationDirectory(
            path=self.source_path,
            role="application",
            destination_name="Application",
            size_bytes=(
                self.primary_size_bytes if self.primary_size_bytes is not None else self.size_bytes
            ),
        )
        return (primary, *self.related_directories)


@dataclass(frozen=True, slots=True)
class DirectoryStats:
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class MigrationRequest:
    source: Path
    destination_base: Path
    destination_relative: Path | None = None


@dataclass(frozen=True, slots=True)
class MigrationResult:
    source: Path
    destination: Path
    stats: DirectoryStats
