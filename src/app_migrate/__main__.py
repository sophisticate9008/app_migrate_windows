from __future__ import annotations

import sys
from ctypes import windll

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app_migrate.language import language
from app_migrate.resources import resource_path
from app_migrate.ui.main_window import MainWindow
from app_migrate.ui.style import apply_fluent_theme


def main() -> int:
    windll.shell32.SetCurrentProcessExplicitAppUserModelID("AppMigrate.Windows")
    app = QApplication(sys.argv)
    app.setApplicationName(language.lang("app_name"))
    app.setOrganizationName("AppMigrate")
    app.setWindowIcon(QIcon(str(resource_path("icons/app-migrate.ico"))))
    apply_fluent_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
