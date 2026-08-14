from __future__ import annotations

import json
from pathlib import Path


class Language:
    def __init__(self) -> None:
        resource_path = Path(__file__).with_name("resources") / "zhlang.json"
        with resource_path.open("r", encoding="utf-8") as file:
            self._strings: dict[str, str] = json.load(file)

    def lang(self, key: str, **values: object) -> str:
        text = self._strings.get(key, key)
        return text.format(**values) if values else text


language = Language()
