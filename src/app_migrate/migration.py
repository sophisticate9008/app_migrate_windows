from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from app_migrate.models import DirectoryStats, MigrationRequest, MigrationResult
from app_migrate.path_utils import is_dangerous_source, is_relative_to, safe_component


class MigrationError(RuntimeError):
    pass


ProgressCallback = Callable[[str], None]


def directory_stats(path: Path) -> DirectoryStats:
    file_count = 0
    total_bytes = 0
    for root, directory_names, file_names in os.walk(path, followlinks=False):
        directory_names[:] = [
            name
            for name in directory_names
            if not (Path(root) / name).is_symlink() and not (Path(root) / name).is_junction()
        ]
        for name in file_names:
            file_path = Path(root) / name
            try:
                if not file_path.is_symlink():
                    file_count += 1
                    total_bytes += file_path.stat().st_size
            except OSError as error:
                raise MigrationError(str(error)) from error
    return DirectoryStats(file_count=file_count, total_bytes=total_bytes)


def validate_request(request: MigrationRequest) -> tuple[Path, Path]:
    source = request.source.absolute()
    destination_base = request.destination_base.resolve(strict=False)
    if not source.exists() or not source.is_dir():
        raise MigrationError("source_not_directory")
    if source.is_symlink() or source.is_junction() or os.path.islink(source):
        raise MigrationError("source_is_link")
    if is_dangerous_source(source):
        raise MigrationError("source_is_protected")
    if not destination_base.exists() or not destination_base.is_dir():
        raise MigrationError("destination_not_directory")
    if source.drive.casefold() == destination_base.drive.casefold():
        raise MigrationError("destination_same_drive")
    if is_relative_to(destination_base, source):
        raise MigrationError("destination_inside_source")

    if request.destination_relative is None:
        destination = destination_base / safe_component(source.name)
    else:
        relative = request.destination_relative
        if relative.is_absolute() or ".." in relative.parts:
            raise MigrationError("destination_relative_invalid")
        destination = (destination_base / relative).resolve(strict=False)
        if not is_relative_to(destination, destination_base):
            raise MigrationError("destination_relative_invalid")
    if destination.exists():
        raise MigrationError("destination_exists")
    return source, destination


def _run_robocopy(source: Path, destination: Path) -> None:
    command = [
        "robocopy",
        str(source),
        str(destination),
        "/E",
        "/COPY:DAT",
        "/DCOPY:DAT",
        "/R:2",
        "/W:1",
        "/XJ",
        "/NP",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if process.returncode >= 8:
        details = (process.stderr or process.stdout).strip()
        raise MigrationError(f"robocopy_failed:{details}")


def _create_junction(link: Path, target: Path) -> None:
    script = (
        "& { $linkPath = $env:APP_MIGRATE_LINK_PATH; "
        "$targetPath = $env:APP_MIGRATE_TARGET_PATH; "
        "New-Item -ItemType Junction -Path $linkPath -Target $targetPath "
        "-ErrorAction Stop | Out-Null }"
    )
    process_environment = os.environ.copy()
    process_environment["APP_MIGRATE_LINK_PATH"] = str(link)
    process_environment["APP_MIGRATE_TARGET_PATH"] = str(target)
    process = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        env=process_environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if process.returncode != 0:
        raise MigrationError(f"junction_failed:{(process.stderr or process.stdout).strip()}")


def migrate_directory(
    request: MigrationRequest,
    progress: ProgressCallback | None = None,
) -> MigrationResult:
    notify = progress or (lambda _message: None)
    source, destination = validate_request(request)
    operation_id = uuid.uuid4().hex[:10]
    staging = destination.with_name(f"{destination.name}.app_migrate_partial_{operation_id}")
    backup = source.with_name(f"{source.name}.app_migrate_backup_{operation_id}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    notify("calculating")
    source_stats = directory_stats(source)
    try:
        notify("copying")
        _run_robocopy(source, staging)
        notify("verifying")
        copied_stats = directory_stats(staging)
        if copied_stats != source_stats:
            raise MigrationError("verification_failed")

        source.rename(backup)
        try:
            staging.rename(destination)
            _create_junction(source, destination)
            if (
                not source.exists()
                or not source.is_dir()
                or not os.path.samefile(source, destination)
            ):
                raise MigrationError("junction_verification_failed")
        except Exception:
            if source.exists() or source.is_symlink() or source.is_junction():
                with suppress(OSError):
                    source.rmdir()
            if destination.exists() and not staging.exists():
                destination.rename(staging)
            if backup.exists() and not source.exists():
                backup.rename(source)
            raise

        notify("cleaning")
        shutil.rmtree(backup)
        notify("completed")
        return MigrationResult(source=source, destination=destination, stats=source_stats)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
