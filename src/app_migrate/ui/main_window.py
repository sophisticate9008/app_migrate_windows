from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    MSFluentWindow,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from app_migrate.language import language
from app_migrate.migration import migrate_directory
from app_migrate.models import InstalledApplication, MigrationRequest, MigrationResult
from app_migrate.registry_scanner import scan_installed_applications
from app_migrate.workers import FunctionWorker


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _batch_migrate(
    requests: list[MigrationRequest], progress: object
) -> tuple[list[MigrationResult], list[str]]:
    results: list[MigrationResult] = []
    errors: list[str] = []
    emit = getattr(progress, "emit", progress)
    for request in requests:
        try:
            results.append(migrate_directory(request, progress=emit))
        except Exception as error:
            errors.append(f"{request.source}: {error}")
    return results, errors


class MainWindow(MSFluentWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(language.lang("app_name"))
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)
        self._thread_pool = QThreadPool.globalInstance()
        self._applications: list[InstalledApplication] = []
        self._active_workers: set[FunctionWorker] = set()
        self._build_ui()

    def _build_ui(self) -> None:
        applications_page = self._build_applications_page()
        custom_page = self._build_custom_page()
        self.addSubInterface(
            applications_page, FluentIcon.APPLICATION, language.lang("tab_applications")
        )
        self.addSubInterface(custom_page, FluentIcon.LINK, language.lang("tab_custom"))

    def _page_header(self, title_key: str, description_key: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.addWidget(SubtitleLabel(language.lang(title_key)))
        description = BodyLabel(language.lang(description_key))
        description.setWordWrap(True)
        layout.addWidget(description)
        return layout

    def _build_applications_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("applicationsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(18)
        layout.addLayout(self._page_header("tab_applications", "applications_description"))

        toolbar = QHBoxLayout()
        self.scan_button = self._button("scan_registry", FluentIcon.SYNC, self._scan_registry)
        self.select_all_button = self._button("select_all", FluentIcon.ACCEPT, self._select_all)
        self.clear_button = self._button(
            "clear_selection", FluentIcon.CANCEL, self._clear_selection
        )
        toolbar.addWidget(self.scan_button)
        toolbar.addWidget(self.select_all_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.app_table = TableWidget(page)
        self.app_table.setColumnCount(4)
        self.app_table.setHorizontalHeaderLabels(
            [
                language.lang("application"),
                language.lang("publisher"),
                language.lang("version"),
                language.lang("source_directory"),
            ]
        )
        self.app_table.setAlternatingRowColors(True)
        self.app_table.setWordWrap(False)
        self.app_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.app_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.app_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.app_table.verticalHeader().hide()
        header = self.app_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.app_table, 1)

        destination_layout, self.app_destination, app_browse = self._path_field(
            "destination_base", "choose_destination", self._browse_app_destination
        )
        layout.addLayout(destination_layout)
        intermediate_layout = QHBoxLayout()
        intermediate_label = QLabel(language.lang("intermediate_directory"))
        intermediate_label.setFixedWidth(120)
        self.app_intermediate = LineEdit()
        self.app_intermediate.setText(language.lang("default_intermediate"))
        intermediate_layout.addWidget(intermediate_label)
        intermediate_layout.addWidget(self.app_intermediate, 1)
        intermediate_layout.addSpacing(app_browse.sizeHint().width())
        layout.addLayout(intermediate_layout)

        action_layout = QHBoxLayout()
        self.app_status = CaptionLabel(language.lang("status_ready"))
        self.app_progress = ProgressBar()
        self.app_progress.setFixedWidth(150)
        self.app_progress.hide()
        action_layout.addWidget(self.app_status)
        action_layout.addWidget(self.app_progress)
        action_layout.addStretch(1)
        self.app_migrate_button = self._button(
            "migrate_selected", FluentIcon.SEND, self._migrate_selected, accent=True
        )
        action_layout.addWidget(self.app_migrate_button)
        layout.addLayout(action_layout)
        return page

    def _build_custom_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("customPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(18)
        layout.addLayout(self._page_header("tab_custom", "custom_tip"))

        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 20, 0, 0)
        section_layout.setSpacing(16)
        source_layout, self.custom_source, _ = self._path_field(
            "custom_source", "choose_source", self._browse_custom_source
        )
        destination_layout, self.custom_destination, browse = self._path_field(
            "destination_base", "choose_destination", self._browse_custom_destination
        )
        section_layout.addLayout(source_layout)
        section_layout.addLayout(destination_layout)
        intermediate_layout = QHBoxLayout()
        label = QLabel(language.lang("intermediate_directory"))
        label.setFixedWidth(120)
        self.custom_intermediate = LineEdit()
        self.custom_intermediate.setText(language.lang("default_intermediate"))
        intermediate_layout.addWidget(label)
        intermediate_layout.addWidget(self.custom_intermediate, 1)
        intermediate_layout.addSpacing(browse.sizeHint().width())
        section_layout.addLayout(intermediate_layout)
        layout.addWidget(section)
        layout.addStretch(1)

        action_layout = QHBoxLayout()
        self.custom_status = CaptionLabel(language.lang("status_ready"))
        self.custom_progress = ProgressBar()
        self.custom_progress.setFixedWidth(150)
        self.custom_progress.hide()
        action_layout.addWidget(self.custom_status)
        action_layout.addWidget(self.custom_progress)
        action_layout.addStretch(1)
        self.custom_migrate_button = self._button(
            "migrate_directory", FluentIcon.SEND, self._migrate_custom, accent=True
        )
        action_layout.addWidget(self.custom_migrate_button)
        layout.addLayout(action_layout)
        return page

    def _button(
        self,
        text_key: str,
        icon: FluentIcon,
        callback: object,
        accent: bool = False,
    ) -> PushButton:
        button_type = PrimaryPushButton if accent else PushButton
        button = button_type(icon, language.lang(text_key))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)  # type: ignore[arg-type]
        return button

    def _path_field(
        self, label_key: str, dialog_key: str, callback: object
    ) -> tuple[QHBoxLayout, LineEdit, PushButton]:
        layout = QHBoxLayout()
        label = QLabel(language.lang(label_key))
        label.setFixedWidth(120)
        line_edit = LineEdit()
        browse = self._button("browse", FluentIcon.FOLDER, callback)
        browse.setToolTip(language.lang(dialog_key))
        layout.addWidget(label)
        layout.addWidget(line_edit, 1)
        layout.addWidget(browse)
        return layout, line_edit, browse

    def _choose_directory(self, title_key: str, target: LineEdit) -> None:
        initial = target.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, language.lang(title_key), initial)
        if path:
            target.setText(path)

    def _browse_app_destination(self) -> None:
        self._choose_directory("choose_destination", self.app_destination)

    def _browse_custom_source(self) -> None:
        self._choose_directory("choose_source", self.custom_source)

    def _browse_custom_destination(self) -> None:
        self._choose_directory("choose_destination", self.custom_destination)

    def _scan_registry(self) -> None:
        self._set_busy(True, "status_scanning")
        worker = FunctionWorker(scan_installed_applications)
        worker.signals.result.connect(self._populate_applications)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self._finish_worker(worker))
        self._start_worker(worker)

    def _populate_applications(self, applications: object) -> None:
        self._applications = list(applications)  # type: ignore[arg-type]
        self.app_table.setRowCount(len(self._applications))
        for row, application in enumerate(self._applications):
            name_item = QTableWidgetItem(application.name)
            name_item.setCheckState(Qt.CheckState.Unchecked)
            name_item.setToolTip(application.registry_path)
            self.app_table.setItem(row, 0, name_item)
            publisher_item = QTableWidgetItem(application.publisher)
            version_item = QTableWidgetItem(application.version)
            source_item = QTableWidgetItem(str(application.source_path))
            source_item.setToolTip(str(application.source_path))
            self.app_table.setItem(row, 1, publisher_item)
            self.app_table.setItem(row, 2, version_item)
            self.app_table.setItem(row, 3, source_item)
        self._set_status(language.lang("status_found", count=len(self._applications)))

    def _select_all(self) -> None:
        for row in range(self.app_table.rowCount()):
            self.app_table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    def _clear_selection(self) -> None:
        for row in range(self.app_table.rowCount()):
            self.app_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)

    def _migrate_selected(self) -> None:
        selected = [
            application
            for row, application in enumerate(self._applications)
            if self.app_table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            self._notify_warning(language.lang("select_application"))
            return
        destination = Path(self.app_destination.text().strip())
        if not destination.is_dir():
            self._notify_warning(language.lang("missing_destination"))
            return
        if not self._confirm(len(selected)):
            return
        requests = [
            MigrationRequest(application.source_path, destination, self.app_intermediate.text())
            for application in selected
        ]
        self._start_migration(requests)

    def _migrate_custom(self) -> None:
        source = Path(self.custom_source.text().strip())
        destination = Path(self.custom_destination.text().strip())
        if not source.is_dir():
            self._notify_warning(language.lang("missing_source"))
            return
        if not destination.is_dir():
            self._notify_warning(language.lang("missing_destination"))
            return
        if not self._confirm(1):
            return
        request = MigrationRequest(source, destination, self.custom_intermediate.text())
        self._start_migration([request])

    def _confirm(self, count: int) -> bool:
        dialog = MessageBox(
            language.lang("warning_title"),
            language.lang("confirm_migration", count=count),
            self,
        )
        dialog.yesButton.setText(language.lang("continue_action"))
        dialog.cancelButton.setText(language.lang("cancel_action"))
        return bool(dialog.exec())

    def _start_migration(self, requests: list[MigrationRequest]) -> None:
        self._set_busy(True, "status_calculating")
        worker = FunctionWorker(_batch_migrate, requests, with_progress=True)
        worker.signals.progress.connect(self._update_progress)
        worker.signals.result.connect(self._migration_finished)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(lambda: self._finish_worker(worker))
        self._start_worker(worker)

    def _migration_finished(self, result: object) -> None:
        results, errors = result  # type: ignore[misc]
        if errors:
            details = "\n".join(self._friendly_error(error) for error in errors)
            summary = language.lang("batch_summary", success=len(results), failed=len(errors))
            InfoBar.warning(
                title=language.lang("warning_title"),
                content=f"{summary}\n{details}",
                duration=-1,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        elif len(results) == 1:
            migration = results[0]
            InfoBar.success(
                title=language.lang("status_completed"),
                content=language.lang(
                    "migration_summary",
                    source=migration.source,
                    destination=migration.destination,
                    size=_format_size(migration.stats.total_bytes),
                ),
                duration=8000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            InfoBar.success(
                title=language.lang("status_completed"),
                content=language.lang("batch_summary", success=len(results), failed=0),
                duration=5000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _update_progress(self, stage: str) -> None:
        self._set_status(language.lang(f"status_{stage}"))

    def _friendly_error(self, error: str) -> str:
        error_code = error.rsplit(": ", 1)[-1].split(":", 1)[0]
        translated = language.lang(error_code)
        return translated if translated != error_code else error

    def _show_error(self, error: str) -> None:
        InfoBar.error(
            title=language.lang("error_title"),
            content=self._friendly_error(error),
            duration=-1,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _notify_warning(self, content: str) -> None:
        InfoBar.warning(
            title=language.lang("warning_title"),
            content=content,
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _set_status(self, text: str) -> None:
        self.app_status.setText(text)
        self.custom_status.setText(text)

    def _set_busy(self, busy: bool, status_key: str = "status_ready") -> None:
        self.scan_button.setEnabled(not busy)
        self.app_migrate_button.setEnabled(not busy)
        self.custom_migrate_button.setEnabled(not busy)
        for progress_bar in (self.app_progress, self.custom_progress):
            progress_bar.setRange(0, 0 if busy else 100)
            progress_bar.setVisible(busy)
        self._set_status(language.lang(status_key))

    def _start_worker(self, worker: FunctionWorker) -> None:
        self._active_workers.add(worker)
        self._thread_pool.start(worker)

    def _finish_worker(self, worker: FunctionWorker) -> None:
        self._active_workers.discard(worker)
        self._set_busy(False)

    def closeEvent(self, event: object) -> None:
        if self._active_workers:
            self._notify_warning(language.lang("operation_in_progress"))
            event.ignore()
            return
        super().closeEvent(event)  # type: ignore[arg-type]
