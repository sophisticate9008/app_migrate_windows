from __future__ import annotations

import os
import winreg
from dataclasses import replace
from pathlib import Path

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


def _directory_size(path: Path) -> int | None:
    total_bytes = 0
    failed = False

    def handle_error(_error: OSError) -> None:
        nonlocal failed
        failed = True

    for root, directory_names, file_names in os.walk(path, followlinks=False, onerror=handle_error):
        directory_names[:] = [
            name
            for name in directory_names
            if not (Path(root) / name).is_symlink() and not (Path(root) / name).is_junction()
        ]
        for name in file_names:
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
        if candidate and candidate.is_dir() and not is_dangerous_source(candidate):
            return candidate
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
                        application = InstalledApplication(
                            name=name,
                            source_path=path,
                            icon_path=extract_file_path(_query_string(subkey, "DisplayIcon")),
                            size_bytes=estimated_kilobytes * 1024 if estimated_kilobytes else None,
                            publisher=_query_string(subkey, "Publisher"),
                            version=_query_string(subkey, "DisplayVersion"),
                            registry_path=f"{root_name}\\{_UNINSTALL_KEY}\\{subkey_name}",
                        )
                        existing = applications.get(key)
                        if existing is None or (
                            existing.size_bytes is None and application.size_bytes is not None
                        ):
                            applications[key] = application

    for key, application in tuple(applications.items()):
        if application.size_bytes is None:
            applications[key] = replace(
                application,
                size_bytes=_directory_size(application.source_path),
            )

    return sorted(applications.values(), key=lambda item: item.name.casefold())
