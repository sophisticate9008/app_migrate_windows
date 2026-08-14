from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psutil

from app_migrate.models import InstalledApplication


@dataclass(frozen=True, slots=True)
class RunningProcess:
    pid: int
    name: str


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


def _path_is_within(path: str | Path, directory: Path) -> bool:
    try:
        Path(_normalized_path(path)).relative_to(_normalized_path(directory))
        return True
    except ValueError:
        return False


def find_running_application_processes(
    applications: list[InstalledApplication],
) -> list[RunningProcess]:
    source_directories = [application.source_path for application in applications]
    executable_paths = {
        _normalized_path(application.icon_path)
        for application in applications
        if application.icon_path and application.icon_path.suffix.casefold() == ".exe"
    }
    matches: dict[int, RunningProcess] = {}

    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            pid = int(process.info["pid"])
            executable = process.info.get("exe")
            if pid == os.getpid() or not executable:
                continue
            normalized_executable = _normalized_path(executable)
            if normalized_executable not in executable_paths and not any(
                _path_is_within(executable, source) for source in source_directories
            ):
                continue
            matches[pid] = RunningProcess(
                pid=pid,
                name=str(process.info.get("name") or Path(executable).name),
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            continue

    return sorted(matches.values(), key=lambda item: (item.name.casefold(), item.pid))
