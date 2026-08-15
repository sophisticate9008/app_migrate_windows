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
    executable: Path


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
                executable=Path(executable),
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
            continue

    return sorted(matches.values(), key=lambda item: (item.name.casefold(), item.pid))


def terminate_application_processes(
    processes: list[RunningProcess],
    timeout: float = 3.0,
) -> list[RunningProcess]:
    """Terminate matching processes and return those that could not be stopped."""
    pending: dict[psutil.Process, RunningProcess] = {}
    failed: dict[int, RunningProcess] = {}

    for running in processes:
        try:
            process = psutil.Process(running.pid)
            if _normalized_path(process.exe()) != _normalized_path(running.executable):
                continue
            process.terminate()
            pending[process] = running
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
            failed[running.pid] = running

    _gone, alive = psutil.wait_procs(list(pending), timeout=timeout)
    for process in alive:
        running = pending[process]
        try:
            process.kill()
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
            failed[running.pid] = running

    _gone, alive = psutil.wait_procs(alive, timeout=timeout)
    for process in alive:
        running = pending[process]
        failed[running.pid] = running

    return sorted(failed.values(), key=lambda item: (item.name.casefold(), item.pid))
