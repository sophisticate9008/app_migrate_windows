from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QFileInfo, QSettings, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QIcon, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFileIconProvider,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
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
    SearchLineEdit,
    SimpleCardWidget,
    SubtitleLabel,
    TableWidget,
    TextEdit,
)

from app_migrate.application_directories import application_migration_requests
from app_migrate.language import language
from app_migrate.migration import migrate_directory
from app_migrate.models import InstalledApplication, MigrationRequest, MigrationResult
from app_migrate.registry_scanner import scan_installed_applications
from app_migrate.resources import resource_path
from app_migrate.workers import FunctionWorker


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B" or value >= 100:
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _format_date(value: date | None) -> str:
    return value.isoformat() if value else "-"


class SizeTableWidgetItem(QTableWidgetItem):
    def __init__(self, size_bytes: int | None) -> None:
        super().__init__(_format_size(size_bytes) if size_bytes is not None else "-")
        self.setData(Qt.ItemDataRole.UserRole, size_bytes)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        own_size = self.data(Qt.ItemDataRole.UserRole)
        other_size = other.data(Qt.ItemDataRole.UserRole)
        return (-1 if own_size is None else own_size) < (-1 if other_size is None else other_size)


class DateTableWidgetItem(QTableWidgetItem):
    def __init__(self, install_date: date | None) -> None:
        super().__init__(_format_date(install_date))
        ordinal = install_date.toordinal() if install_date else None
        self.setData(Qt.ItemDataRole.UserRole, ordinal)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        own_date = self.data(Qt.ItemDataRole.UserRole)
        other_date = other.data(Qt.ItemDataRole.UserRole)
        return (-1 if own_date is None else own_date) < (-1 if other_date is None else other_date)


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
        self.setWindowIcon(QIcon(str(resource_path("icons/app-migrate.ico"))))
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(2)
        self._settings = QSettings("AppMigrate", "AppMigrate")
        self._applications: list[InstalledApplication] = []
        self._icon_provider = QFileIconProvider()
        self._active_workers: set[FunctionWorker] = set()
        self._build_ui()
        QTimer.singleShot(0, self._scan_registry)

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

        header = QVBoxLayout()
        header.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(16)
        title_row.addWidget(SubtitleLabel(language.lang("tab_applications")))
        self.app_search = SearchLineEdit()
        self.app_search.setPlaceholderText(language.lang("search_applications"))
        self.app_search.setClearButtonEnabled(True)
        self.app_search.setFixedWidth(280)
        self.app_search.textChanged.connect(self._filter_applications)
        title_row.addWidget(self.app_search)
        title_row.addStretch(1)
        header.addLayout(title_row)
        description = BodyLabel(language.lang("applications_description"))
        description.setWordWrap(True)
        header.addWidget(description)
        layout.addLayout(header)

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

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.addWidget(self._build_application_details())

        right_panel = QWidget()
        right_panel.setMinimumWidth(520)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.setSpacing(12)

        self.app_table = TableWidget(right_panel)
        self.app_table.setColumnCount(4)
        self.app_table.setHorizontalHeaderLabels(
            [
                language.lang("application"),
                language.lang("application_drive"),
                language.lang("application_size"),
                language.lang("install_date"),
            ]
        )
        self.app_table.setAlternatingRowColors(True)
        self.app_table.setWordWrap(False)
        self.app_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.app_table.setIconSize(QSize(28, 28))
        self.app_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.app_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.app_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.app_table.verticalHeader().hide()
        self.app_table.verticalHeader().setDefaultSectionSize(40)
        header = self.app_table.horizontalHeader()
        header.setMinimumSectionSize(70)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.app_table.setColumnWidth(1, 70)
        self.app_table.setColumnWidth(2, 90)
        self.app_table.setColumnWidth(3, 112)
        self.app_table.setMinimumWidth(520)
        self.app_table.itemSelectionChanged.connect(self._show_current_application_details)
        self.app_table.model().layoutChanged.connect(
            lambda: QTimer.singleShot(0, self._select_first_application)
        )
        right_layout.addWidget(self.app_table, 1)
        content_splitter.addWidget(right_panel)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setSizes([250, 760])

        destination_layout, self.app_destination, _ = self._path_field(
            "destination_base", "choose_destination", self._browse_app_destination
        )
        self.app_destination.setText(self._restore_path("paths/application_destination"))
        self.app_destination.editingFinished.connect(
            lambda: self._remember_path(
                "paths/application_destination", self.app_destination.text()
            )
        )
        right_layout.addLayout(destination_layout)

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
        right_layout.addLayout(action_layout)
        layout.addWidget(content_splitter, 1)
        return page

    def _build_application_details(self) -> QWidget:
        panel = SimpleCardWidget()
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(320)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(5)

        self.detail_icon = QLabel()
        self.detail_icon.setFixedSize(46, 46)
        self.detail_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_name = SubtitleLabel(language.lang("detail_select_prompt"))
        self.detail_name.setWordWrap(True)
        panel_layout.addWidget(self.detail_icon, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_layout.addWidget(self.detail_name)

        self.detail_values: dict[str, BodyLabel | TextEdit] = {}
        for label_key, value_key, text_height in (
            ("related_directories", "source", 116),
            ("application_size", "size", 0),
            ("install_date", "install_date", 0),
            ("version", "version", 0),
            ("publisher", "publisher", 0),
            ("registry_location", "registry", 72),
        ):
            panel_layout.addSpacing(4)
            panel_layout.addWidget(CaptionLabel(language.lang(label_key)))
            if text_height:
                value_label = TextEdit()
                value_label.setReadOnly(True)
                value_label.setFixedHeight(text_height)
                value_label.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
                value_label.setText(language.lang("detail_empty"))
            else:
                value_label = BodyLabel(language.lang("detail_empty"))
                value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.detail_values[value_key] = value_label
            panel_layout.addWidget(value_label)
        panel_layout.addStretch(1)
        return panel

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
        destination_layout, self.custom_destination, _ = self._path_field(
            "destination_base", "choose_destination", self._browse_custom_destination
        )
        self.custom_destination.setText(self._restore_path("paths/custom_destination"))
        self.custom_destination.editingFinished.connect(
            lambda: self._remember_path("paths/custom_destination", self.custom_destination.text())
        )
        section_layout.addLayout(source_layout)
        section_layout.addLayout(destination_layout)
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

    def _choose_directory(
        self, title_key: str, target: LineEdit, setting_key: str | None = None
    ) -> None:
        initial = target.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, language.lang(title_key), initial)
        if path:
            target.setText(path)
            if setting_key:
                self._remember_path(setting_key, path)

    def _restore_path(self, setting_key: str) -> str:
        return str(self._settings.value(setting_key, ""))

    def _remember_path(self, setting_key: str, path: str) -> None:
        normalized = path.strip()
        if normalized:
            self._settings.setValue(setting_key, normalized)
            self._settings.sync()

    def _browse_app_destination(self) -> None:
        self._choose_directory(
            "choose_destination", self.app_destination, "paths/application_destination"
        )

    def _browse_custom_source(self) -> None:
        self._choose_directory("choose_source", self.custom_source)

    def _browse_custom_destination(self) -> None:
        self._choose_directory(
            "choose_destination", self.custom_destination, "paths/custom_destination"
        )

    def _scan_registry(self) -> None:
        self._set_busy(True, "status_scanning")
        QTimer.singleShot(0, self._perform_registry_scan)

    def _perform_registry_scan(self) -> None:
        try:
            applications = scan_installed_applications()
        except Exception as error:
            self._show_error(str(error))
            self._set_busy(False)
            return
        self._set_busy(False)
        self._populate_applications(applications)

    def _populate_applications(self, applications: object) -> None:
        self._applications = list(applications)  # type: ignore[arg-type]
        self.app_table.setSortingEnabled(False)
        self.app_table.setRowCount(len(self._applications))
        for row, application in enumerate(self._applications):
            name_item = QTableWidgetItem(application.name)
            name_item.setIcon(self._application_icon(application))
            name_item.setCheckState(Qt.CheckState.Unchecked)
            name_item.setToolTip(application.name)
            name_item.setData(Qt.ItemDataRole.UserRole, application)
            self.app_table.setItem(row, 0, name_item)
            drives = sorted({directory.path.drive.upper() for directory in application.directories})
            drive_item = QTableWidgetItem(" / ".join(drives))
            drive_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            size_item = SizeTableWidgetItem(application.size_bytes)
            install_date_item = DateTableWidgetItem(application.install_date)
            self.app_table.setItem(row, 1, drive_item)
            self.app_table.setItem(row, 2, size_item)
            self.app_table.setItem(row, 3, install_date_item)
        self.app_table.setSortingEnabled(True)
        self.app_table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self._filter_applications(self.app_search.text())

    def _filter_applications(self, search_text: str) -> None:
        query = search_text.strip().casefold()
        visible_count = 0
        first_visible_row = -1
        for row in range(self.app_table.rowCount()):
            name_item = self.app_table.item(row, 0)
            is_visible = not query or query in name_item.text().casefold()
            self.app_table.setRowHidden(row, not is_visible)
            if is_visible:
                visible_count += 1
                if first_visible_row < 0:
                    first_visible_row = row

        current_row = self.app_table.currentRow()
        if first_visible_row < 0:
            self.app_table.clearSelection()
            self._clear_application_details()
        elif current_row < 0 or self.app_table.isRowHidden(current_row):
            self.app_table.setCurrentCell(first_visible_row, 0)
            self.app_table.selectRow(first_visible_row)
            self._show_current_application_details()

        if query:
            self._set_status(
                language.lang(
                    "status_filtered",
                    visible=visible_count,
                    total=self.app_table.rowCount(),
                )
            )
        else:
            self._set_status(language.lang("status_found", count=self.app_table.rowCount()))

    def _application_icon(self, application: InstalledApplication) -> QIcon:
        if application.icon_path:
            if application.icon_path.suffix.casefold() in {".exe", ".dll"}:
                icon = self._icon_provider.icon(QFileInfo(str(application.icon_path)))
            else:
                icon = QIcon(str(application.icon_path))
            if not icon.isNull():
                return icon
        return FluentIcon.APPLICATION.icon()

    def _show_application_details(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if current_row < 0 or current_row >= self.app_table.rowCount():
            self._clear_application_details()
            return
        application = self.app_table.item(current_row, 0).data(Qt.ItemDataRole.UserRole)
        if not isinstance(application, InstalledApplication):
            self._clear_application_details()
            return
        icon = self._application_icon(application)
        self.detail_icon.setPixmap(icon.pixmap(42, 42))
        self.detail_name.setText(application.name)
        directory_lines = [
            f"{language.lang(f'directory_role_{directory.role}')}\n{directory.path}"
            for directory in application.directories
        ]
        self.detail_values["source"].setText("\n\n".join(directory_lines))
        self.detail_values["size"].setText(
            _format_size(application.size_bytes)
            if application.size_bytes is not None
            else language.lang("detail_empty")
        )
        self.detail_values["install_date"].setText(_format_date(application.install_date))
        self.detail_values["version"].setText(application.version or language.lang("detail_empty"))
        self.detail_values["publisher"].setText(
            application.publisher or language.lang("detail_empty")
        )
        self.detail_values["registry"].setText(application.registry_path)

    def _show_current_application_details(self) -> None:
        self._show_application_details(self.app_table.currentRow(), 0, -1, -1)

    def _select_first_application(self) -> None:
        first_visible_row = next(
            (
                row
                for row in range(self.app_table.rowCount())
                if not self.app_table.isRowHidden(row)
            ),
            -1,
        )
        if first_visible_row < 0:
            self._clear_application_details()
            return
        self.app_table.setCurrentCell(first_visible_row, 0)
        self.app_table.selectRow(first_visible_row)
        self._show_current_application_details()

    def _clear_application_details(self) -> None:
        self.detail_icon.clear()
        self.detail_name.setText(language.lang("detail_select_prompt"))
        for value_label in self.detail_values.values():
            value_label.setText(language.lang("detail_empty"))

    def _select_all(self) -> None:
        for row in range(self.app_table.rowCount()):
            self.app_table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    def _clear_selection(self) -> None:
        for row in range(self.app_table.rowCount()):
            self.app_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)

    def _migrate_selected(self) -> None:
        selected = [
            self.app_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.app_table.rowCount())
            if self.app_table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            self._notify_warning(language.lang("select_application"))
            return
        destination = Path(self.app_destination.text().strip())
        if not destination.is_dir():
            self._notify_warning(language.lang("missing_destination"))
            return
        requests = [
            request
            for application in selected
            for request in application_migration_requests(application, destination)
        ]
        if not self._confirm(len(requests)):
            return
        self._remember_path("paths/application_destination", str(destination))
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
        self._remember_path("paths/custom_destination", str(destination))
        request = MigrationRequest(source, destination)
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
