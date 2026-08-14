from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import patch

from app_migrate.migration import (
    MigrationError,
    _create_junction,
    directory_stats,
    migrate_directory,
    validate_request,
)
from app_migrate.models import DirectoryStats, MigrationRequest
from app_migrate.path_utils import extract_file_path, safe_component


class PathUtilTests(unittest.TestCase):
    def test_safe_component_replaces_windows_invalid_characters(self) -> None:
        self.assertEqual(safe_component("bad:name/with*chars?"), "bad_name_with_chars_")

    def test_extract_file_path_handles_quoted_display_icon_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            icon_path = Path(temporary) / "app icon.exe"
            icon_path.touch()

            extracted = extract_file_path(f'"{icon_path}",0')

            self.assertEqual(extracted, icon_path.resolve())


class MigrationTests(unittest.TestCase):
    def test_validate_rejects_destination_on_same_drive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()

            with self.assertRaisesRegex(MigrationError, "destination_same_drive"):
                validate_request(MigrationRequest(source, destination, "AppMigrate"))

    def test_junction_is_created_and_excluded_from_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            (target / "payload.txt").write_text("payload", encoding="utf-8")
            link = root / "link"

            _create_junction(link, target)
            try:
                self.assertTrue(link.is_junction())
                self.assertEqual((link / "payload.txt").read_text(encoding="utf-8"), "payload")
                self.assertEqual(directory_stats(root), DirectoryStats(file_count=1, total_bytes=7))
            finally:
                link.rmdir()

    def test_validate_rejects_existing_junction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            destination = root / "destination"
            target.mkdir()
            destination.mkdir()
            link = root / "link"
            _create_junction(link, target)
            try:
                with self.assertRaisesRegex(MigrationError, "source_is_link"):
                    validate_request(MigrationRequest(link, destination, "AppMigrate"))
            finally:
                link.rmdir()

    def test_source_is_restored_when_junction_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination" / "source"
            source.mkdir()
            (source / "payload.txt").write_text("payload", encoding="utf-8")
            request = MigrationRequest(source, root, "ignored")

            with (
                patch(
                    "app_migrate.migration.validate_request",
                    return_value=(source, destination),
                ),
                patch("app_migrate.migration._run_robocopy", side_effect=copytree),
                patch(
                    "app_migrate.migration._create_junction",
                    side_effect=MigrationError("junction_failed"),
                ),
                self.assertRaisesRegex(MigrationError, "junction_failed"),
            ):
                migrate_directory(request)

            self.assertTrue(source.is_dir())
            self.assertFalse(source.is_junction())
            self.assertEqual((source / "payload.txt").read_text(encoding="utf-8"), "payload")
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
