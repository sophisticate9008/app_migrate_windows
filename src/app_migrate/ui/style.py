from __future__ import annotations

import winreg

from qfluentwidgets import Theme, setTheme, setThemeColor


def _registry_dword(path: str, name: str, default: int) -> int:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return int(value)
    except (OSError, TypeError, ValueError):
        return default


def _accent_color() -> str:
    raw = _registry_dword(r"Software\Microsoft\Windows\DWM", "ColorizationColor", 0)
    if raw:
        red = (raw >> 16) & 0xFF
        green = (raw >> 8) & 0xFF
        blue = raw & 0xFF
        return f"#{red:02x}{green:02x}{blue:02x}"
    return "#0067c0"


def apply_fluent_theme(_app: object) -> None:
    setTheme(Theme.AUTO)
    setThemeColor(_accent_color())
