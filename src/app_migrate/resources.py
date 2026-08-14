from __future__ import annotations

from pathlib import Path

_RESOURCE_ROOT = Path(__file__).with_name("resources")


def resource_path(relative_path: str) -> Path:
    return _RESOURCE_ROOT / relative_path
