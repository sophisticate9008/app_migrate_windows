from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from shutil import copytree
from unittest.mock import Mock, patch

from app_migrate.application_directories import (
    application_migration_requests,
    program_migration_request,
)
from app_migrate.migration import (
    MigrationError,
    _create_junction,
    _extended_length_path,
    _remove_tree,
    directory_stats,
    migrate_directory,
    validate_request,
)
from app_migrate.models import (
    ApplicationDirectory,
    DirectoryStats,
    InstalledApplication,
    MigrationRequest,
)
from app_migrate.path_utils import (
    directory_link_target,
    extract_file_path,
    normalize_path,
    safe_component,
)
from app_migrate.process_scanner import find_running_application_processes


class PathUtilTests(unittest.TestCase):
    def test_safe_component_replaces_windows_invalid_characters(self) -> None:
        self.assertEqual(safe_component("bad:name/with*chars?"), "bad_name_with_chars_")

    def test_extract_file_path_handles_quoted_display_icon_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            icon_path = Path(temporary) / "app icon.exe"
            icon_path.touch()

            extracted = extract_file_path(f'"{icon_path}",0')

            self.assertEqual(extracted, icon_path.absolute())

    def test_normalize_path_preserves_junction_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            _create_junction(link, target)
            try:
                self.assertEqual(normalize_path(str(link)), link.absolute())
                self.assertEqual(directory_link_target(link), target.resolve())
            finally:
                link.rmdir()


class MigrationTests(unittest.TestCase):
    def test_extended_length_path_supports_windows_long_paths(self) -> None:
        path = Path(r"C:\data\folder")

        self.assertEqual(str(_extended_length_path(path)), r"\\?\C:\data\folder")

    def test_directory_stats_reads_files_beyond_max_path(self) -> None:
        root = Path(tempfile.mkdtemp(dir=Path.cwd()))
        try:
            relative = Path(*(["nested_directory_name_" * 2] * 6), "payload.bin")
            long_file = _extended_length_path(root / relative)
            long_file.parent.mkdir(parents=True)
            long_file.write_bytes(b"payload")
            self.assertGreater(len(str(root / relative)), 260)

            self.assertEqual(directory_stats(root), DirectoryStats(file_count=1, total_bytes=7))
        finally:
            _remove_tree(root, ignore_errors=True)

    def test_finds_running_process_inside_application_directory(self) -> None:
        application = InstalledApplication(
            name="Example",
            source_path=Path(r"D:\Apps\Example"),
        )
        process = Mock()
        process.info = {
            "pid": 123,
            "name": "example.exe",
            "exe": r"D:\Apps\Example\example.exe",
        }

        with (
            patch("app_migrate.process_scanner.psutil.process_iter", return_value=[process]),
            patch("app_migrate.process_scanner.os.getpid", return_value=999),
        ):
            running = find_running_application_processes([application])

        self.assertEqual([(item.pid, item.name) for item in running], [(123, "example.exe")])

    def test_application_directory_group_uses_separate_targets(self) -> None:
        application = InstalledApplication(
            name="Google Chrome",
            source_path=Path(r"C:\Program Files\Google\Chrome"),
            storage_name="Chrome",
            related_directories=(
                ApplicationDirectory(
                    path=Path(r"C:\Users\Tester\AppData\Local\Google\Chrome"),
                    role="user_data",
                    destination_name="UserData",
                ),
            ),
        )

        requests = application_migration_requests(application, Path(r"D:\02.app"))

        self.assertEqual(len(requests), 2)
        self.assertEqual(
            requests[0].destination_relative,
            Path(r"Program Files\Google\Chrome"),
        )
        self.assertEqual(requests[1].destination_relative, Path(r"Chrome\UserData"))

    def test_program_migration_preserves_source_directory_structure(self) -> None:
        application = InstalledApplication(
            name="Example",
            source_path=Path(r"C:\11\22"),
        )

        request = program_migration_request(application, Path(r"D:\migrate"))

        self.assertEqual(request.destination_relative, Path(r"11\22"))

    def test_validate_rejects_destination_on_same_drive(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()

            with self.assertRaisesRegex(MigrationError, "destination_same_drive"):
                validate_request(MigrationRequest(source, destination))

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
                    validate_request(MigrationRequest(link, destination))
            finally:
                link.rmdir()

    def test_source_is_restored_when_junction_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination" / "source"
            source.mkdir()
            (source / "payload.txt").write_text("payload", encoding="utf-8")
            request = MigrationRequest(source, root)

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
