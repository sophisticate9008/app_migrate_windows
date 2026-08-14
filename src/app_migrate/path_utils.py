from __future__ import annotations

import os
import re
from pathlib import Path

_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DRIVE_ROOT = re.compile(r"^[A-Za-z]:\\?$")


def normalize_path(value: str) -> Path | None:
    value = os.path.expandvars(value.strip().strip('"').strip())
    if not value:
        return None
    try:
        path = Path(value).resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return path if path.is_absolute() else None


def extract_executable_path(value: str) -> Path | None:
    value = os.path.expandvars(value.strip())
    if not value:
        return None
    if value.startswith('"'):
        end = value.find('"', 1)
        candidate = value[1:end] if end > 1 else value.strip('"')
    else:
        match = re.search(r"(?i)^(.+?\.(?:exe|ico|dll))(?=,|\s+-|\s+/|$)", value)
        candidate = match.group(1) if match else value.split(",", 1)[0]
    path = normalize_path(candidate)
    return path.parent if path and path.suffix else path


def safe_component(value: str) -> str:
    cleaned = _INVALID_COMPONENT.sub("_", value).strip().rstrip(".")
    return cleaned or "migrated"


def is_dangerous_source(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    text = str(resolved)
    if _DRIVE_ROOT.fullmatch(text):
        return True

    protected = {
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows")).resolve(strict=False),
        Path(os.environ.get("USERPROFILE", r"C:\Users\Default")).resolve(strict=False),
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")).resolve(strict=False),
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")).resolve(strict=False),
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")).resolve(strict=False),
        Path(os.environ.get("SYSTEMDRIVE", "C:") + "\\Users").resolve(strict=False),
    }
    return resolved in protected


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False
