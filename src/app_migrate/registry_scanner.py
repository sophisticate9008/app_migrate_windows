from __future__ import annotations

import os
import winreg
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from time import monotonic

from app_migrate.application_directories import (
    discover_related_directories,
    normalize_application_directory,
)
from app_migrate.models import InstalledApplication
from app_migrate.path_utils import (
    extract_executable_path,
    extract_file_path,
    is_dangerous_source,
    normalize_path,
)

_UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def _query_string(key: winreg.HKEYType, name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return str(value).strip() if value is not None else ""
    except OSError:
        return ""


def _query_positive_int(key: winreg.HKEYType, name: str) -> int | None:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (OSError, TypeError, ValueError):
        return None


def _parse_install_date(value: str) -> date | None:
    normalized = value.strip()
    for date_format in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    return None


def _installation_date(key: winreg.HKEYType, path: Path) -> date | None:
    parsed = _parse_install_date(_query_string(key, "InstallDate"))
    if parsed is not None:
        return parsed
    try:
        return datetime.fromtimestamp(path.stat().st_ctime).date()
    except (OSError, OverflowError, ValueError):
        return None


def _directory_size(path: Path, deadline: float) -> int | None:
    total_bytes = 0
    failed = False

    def handle_error(_error: OSError) -> None:
        nonlocal failed
        failed = True

    for root, directory_names, file_names in os.walk(path, followlinks=False, onerror=handle_error):
        if monotonic() >= deadline:
            return None
        directory_names[:] = [
            name
            for name in directory_names
            if not (Path(root) / name).is_symlink() and not (Path(root) / name).is_junction()
        ]
        for name in file_names:
            if monotonic() >= deadline:
                return None
            try:
                file_path = Path(root) / name
                if not file_path.is_symlink():
                    total_bytes += file_path.stat().st_size
            except OSError:
                failed = True
    return None if failed else total_bytes


def _candidate_path(key: winreg.HKEYType) -> Path | None:
    install_location = normalize_path(_query_string(key, "InstallLocation"))
    candidates = [
        install_location,
        extract_executable_path(_query_string(key, "DisplayIcon")),
        extract_executable_path(_query_string(key, "UninstallString")),
    ]
    for candidate in candidates:
        if candidate:
            source = normalize_application_directory(candidate)
            if source.is_dir() and not is_dangerous_source(source):
                return source
    return None


def scan_installed_applications() -> list[InstalledApplication]:
    applications: dict[str, InstalledApplication] = {}
    roots = ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM"))
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)

    for root, root_name in roots:
        for view in views:
            try:
                base = winreg.OpenKey(root, _UNINSTALL_KEY, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with base:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(base, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        subkey = winreg.OpenKey(base, subkey_name)
                    except OSError:
                        continue
                    with subkey:
                        name = _query_string(subkey, "DisplayName")
                        path = _candidate_path(subkey)
                        if not name or path is None:
                            continue
                        key = os.path.normcase(str(path.resolve(strict=False)))
                        estimated_kilobytes = _query_positive_int(subkey, "EstimatedSize")
                        icon_path = extract_file_path(_query_string(subkey, "DisplayIcon"))
                        publisher = _query_string(subkey, "Publisher")
                        primary_size = estimated_kilobytes * 1024 if estimated_kilobytes else None
                        application = InstalledApplication(
                            name=name,
                            source_path=path,
                            icon_path=icon_path,
                            size_bytes=primary_size,
                            install_date=_installation_date(subkey, path),
                            publisher=publisher,
                            version=_query_string(subkey, "DisplayVersion"),
                            registry_path=f"{root_name}\\{_UNINSTALL_KEY}\\{subkey_name}",
                            storage_name=path.name,
                            primary_size_bytes=primary_size,
                            related_directories=discover_related_directories(
                                path,
                                publisher,
                                icon_path,
                            ),
                        )
                        existing = applications.get(key)
                        if existing is None or (
                            existing.size_bytes is None and application.size_bytes is not None
                        ):
                            applications[key] = application

    size_deadline = monotonic() + 3
    for key, application in tuple(applications.items()):
        if monotonic() >= size_deadline:
            break
        primary_size = application.primary_size_bytes
        if primary_size is None:
            primary_size = _directory_size(application.source_path, size_deadline)

        related_directories = []
        related_size = 0
        for directory in application.related_directories:
            size_bytes = directory.size_bytes
            if size_bytes is None and monotonic() < size_deadline:
                size_bytes = _directory_size(directory.path, size_deadline)
            related_directories.append(replace(directory, size_bytes=size_bytes))
            if size_bytes is not None:
                related_size += size_bytes

        total_size = primary_size + related_size if primary_size is not None else None
        applications[key] = replace(
            application,
            size_bytes=total_size,
            primary_size_bytes=primary_size,
            related_directories=tuple(related_directories),
        )

    return sorted(applications.values(), key=lambda item: item.name.casefold())
