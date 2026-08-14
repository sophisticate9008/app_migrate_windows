from __future__ import annotations

import subprocess
import sys
from ctypes import windll, wintypes
from pathlib import Path

from app_migrate.language import language

_ERROR_ICON = 0x10
_SHOW_NORMAL = 1


def is_process_elevated() -> bool:
    try:
        return bool(windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def _shell_execute_as_admin(
    executable: str,
    parameters: str,
    working_directory: str,
) -> int:
    shell_execute = windll.shell32.ShellExecuteW
    shell_execute.restype = wintypes.HINSTANCE
    result = shell_execute(
        None,
        "runas",
        executable,
        parameters,
        working_directory,
        _SHOW_NORMAL,
    )
    return int(result or 0)


def request_elevation(
    executable: str | None = None,
    working_directory: Path | None = None,
) -> bool:
    python_executable = executable or sys.executable
    launch_directory = working_directory or Path.cwd()
    parameters = subprocess.list2cmdline(["-m", "app_migrate"])
    result = _shell_execute_as_admin(
        python_executable,
        parameters,
        str(launch_directory),
    )
    return result > 32


def show_elevation_error() -> None:
    windll.user32.MessageBoxW(
        None,
        language.lang("admin_elevation_failed"),
        language.lang("admin_required_title"),
        _ERROR_ICON,
    )
