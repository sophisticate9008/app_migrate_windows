from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app_migrate.windows_admin import request_elevation


class WindowsAdminTests(TestCase):
    def test_request_elevation_launches_module_with_runas(self) -> None:
        with patch(
            "app_migrate.windows_admin._shell_execute_as_admin",
            return_value=33,
        ) as shell_execute:
            result = request_elevation(
                executable=r"D:\app\.venv\Scripts\pythonw.exe",
                working_directory=Path(r"D:\app"),
            )

        self.assertTrue(result)
        shell_execute.assert_called_once_with(
            r"D:\app\.venv\Scripts\pythonw.exe",
            "-m app_migrate",
            r"D:\app",
        )

    def test_request_elevation_reports_rejected_request(self) -> None:
        with patch(
            "app_migrate.windows_admin._shell_execute_as_admin",
            return_value=5,
        ):
            self.assertFalse(request_elevation())
