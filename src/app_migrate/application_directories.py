from __future__ import annotations

import os
import re
from pathlib import Path

from app_migrate.models import ApplicationDirectory, InstalledApplication, MigrationRequest
from app_migrate.path_utils import safe_component

_GENERIC_DIRECTORY_NAMES = {"application", "app", "bin", "current"}
_PUBLISHER_SUFFIXES = re.compile(
    r"(?i)\b(?:corporation|corp\.?|inc\.?|incorporated|llc|ltd\.?|limited|company|co\.?)\b"
)


def normalize_application_directory(path: Path) -> Path:
    if path.name.casefold() in _GENERIC_DIRECTORY_NAMES and path.parent.parent != path.parent:
        return path.parent
    return path


def _publisher_name(publisher: str) -> str:
    cleaned = _PUBLISHER_SUFFIXES.sub("", publisher)
    return " ".join(cleaned.replace(",", " ").split()).strip()


def _candidate_names(
    source: Path,
    publisher: str,
    icon_path: Path | None,
) -> tuple[set[str], set[str]]:
    product_names = {source.name}
    if icon_path and icon_path.stem.casefold() not in _GENERIC_DIRECTORY_NAMES:
        product_names.add(icon_path.stem)

    vendor_names = {_publisher_name(publisher), source.parent.name}
    product_names = {name for name in product_names if name}
    vendor_names = {
        name
        for name in vendor_names
        if name and name.casefold() not in {"program files", "program files (x86)", "programdata"}
    }
    return product_names, vendor_names


def _default_data_roots() -> tuple[tuple[str, str, Path], ...]:
    configured_roots = (
        ("user_data", "UserData", os.environ.get("LOCALAPPDATA")),
        ("roaming_data", "RoamingData", os.environ.get("APPDATA")),
        ("shared_data", "SharedData", os.environ.get("PROGRAMDATA")),
    )
    return tuple(
        (role, destination_name, Path(value))
        for role, destination_name, value in configured_roots
        if value
    )


def discover_related_directories(
    source: Path,
    publisher: str,
    icon_path: Path | None,
    data_roots: tuple[tuple[str, str, Path], ...] | None = None,
) -> tuple[ApplicationDirectory, ...]:
    product_names, vendor_names = _candidate_names(source, publisher, icon_path)
    candidates: list[ApplicationDirectory] = []
    seen = {os.path.normcase(str(source.resolve(strict=False)))}

    for role, destination_name, root in data_roots or _default_data_roots():
        if not str(root) or not root.is_dir():
            continue
        products = sorted(product_names, key=str.casefold)
        vendors = sorted(vendor_names, key=str.casefold)
        paths = [root / vendor / product for vendor in vendors for product in products]
        paths.extend(root / product for product in products)
        for path in paths:
            if not path.is_dir():
                continue
            normalized = os.path.normcase(str(path.resolve(strict=False)))
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(
                ApplicationDirectory(
                    path=Path(os.path.abspath(path)),
                    role=role,
                    destination_name=destination_name,
                )
            )
            break

    return tuple(candidates)


def application_migration_requests(
    application: InstalledApplication,
    destination_base: Path,
) -> list[MigrationRequest]:
    requests = [program_migration_request(application, destination_base)]
    requests.extend(
        data_migration_request(application, directory, destination_base)
        for directory in application.related_directories
    )
    return requests


def program_migration_request(
    application: InstalledApplication,
    destination_base: Path,
) -> MigrationRequest:
    source = application.source_path
    try:
        relative_source = source.relative_to(source.anchor)
    except ValueError:
        relative_source = Path(source.name)
    return MigrationRequest(
        source=source,
        destination_base=destination_base,
        destination_relative=Path(
            *(safe_component(component) for component in relative_source.parts)
        ),
    )


def data_migration_request(
    application: InstalledApplication,
    directory: ApplicationDirectory,
    destination_base: Path,
) -> MigrationRequest:
    storage_name = safe_component(application.storage_name or application.source_path.name)
    return MigrationRequest(
        source=directory.path,
        destination_base=destination_base,
        destination_relative=Path(storage_name) / safe_component(directory.destination_name),
    )
