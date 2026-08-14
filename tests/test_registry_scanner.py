from __future__ import annotations

import unittest
from datetime import date

from app_migrate.registry_scanner import _parse_install_date


class RegistryScannerTests(unittest.TestCase):
    def test_parse_compact_install_date(self) -> None:
        self.assertEqual(_parse_install_date("20260814"), date(2026, 8, 14))

    def test_parse_invalid_install_date(self) -> None:
        self.assertIsNone(_parse_install_date("not-a-date"))


if __name__ == "__main__":
    unittest.main()
