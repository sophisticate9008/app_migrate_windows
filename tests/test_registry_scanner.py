from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from app_migrate.application_directories import (
    discover_related_directories,
    normalize_application_directory,
)
from app_migrate.registry_scanner import _parse_install_date


class RegistryScannerTests(unittest.TestCase):
    def test_parse_compact_install_date(self) -> None:
        self.assertEqual(_parse_install_date("20260814"), date(2026, 8, 14))

    def test_parse_invalid_install_date(self) -> None:
        self.assertIsNone(_parse_install_date("not-a-date"))

    def test_normalize_application_directory_uses_product_root(self) -> None:
        path = Path(r"C:\Program Files\Google\Chrome\Application")

        self.assertEqual(
            normalize_application_directory(path),
            Path(r"C:\Program Files\Google\Chrome"),
        )

    def test_normalize_application_directory_removes_version_folder(self) -> None:
        path = Path(r"D:\02.app\youku\9.2.73.1001")

        self.assertEqual(
            normalize_application_directory(path),
            Path(r"D:\02.app\youku"),
        )

    def test_discovers_matching_user_data_without_sibling_products(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Program Files" / "Google" / "Chrome"
            chrome_data = root / "Local" / "Google" / "Chrome"
            drive_data = root / "Local" / "Google" / "Drive"
            source.mkdir(parents=True)
            chrome_data.mkdir(parents=True)
            drive_data.mkdir(parents=True)

            directories = discover_related_directories(
                source,
                "Google LLC",
                source / "Application" / "chrome.exe",
                (("user_data", "UserData", root / "Local"),),
            )

        self.assertEqual(len(directories), 1)
        self.assertEqual(directories[0].path, chrome_data.absolute())
        self.assertEqual(directories[0].destination_name, "UserData")


if __name__ == "__main__":
    unittest.main()
