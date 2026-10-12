from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QSettings, QRectF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .converter import SequenceEntry, convert_project, list_sequence_entries, write_resolve_manifest
from .resolve_transfer import (
    ResolveInstallation,
    ResolveProjectSwitchRequired,
    ResolveTransferError,
    find_resolve_installation,
    installation_from_path,
    temporary_interchange_directory,
    transfer_manifest_to_resolve,
    transfer_xml_to_resolve,
)


TEXT = {
    "ru": {
        "window": "Premiere → Resolve",
        "title": "Перенесите монтаж в Resolve",
        "subtitle": "Выберите проект Premiere и передайте монтаж в DaVinci Resolve Studio.",
        "source": "ПРОЕКТ PREMIERE",
        "drop_title": "Перетащите сюда файл .prproj",
        "drop_hint": "или выберите его на компьютере",
        "choose": "Выбрать проект",
        "change": "Изменить файл",
        "sequence": "Секвенция",
        "select_sequence": "Выберите секвенцию",
        "select_project_first": "Сначала выберите проект Premiere",
        "output_placeholder": "Имя DRP-файла",
        "destination_placeholder": "Папка появится после выбора проекта",
        "destination": "Папка сохранения",
        "browse": "Обзор",
        "output_name": "Имя файла",
        "convert": "Передать проект в Resolve Studio",
        "export_xml": "Сохранить XML",
        "export_fcpxml": "Сохранить FCPXML",
        "busy": "Анализирую проект…",
        "ready": "ГОТОВО К КОНВЕРТАЦИИ",
        "idle": "ОЖИДАЕТ ПРОЕКТ",
        "working": "В РАБОТЕ",
        "complete": "ПЕРЕДАНО В RESOLVE",
        "complete_xml": "XML СОХРАНЁН",
        "failed": "ОШИБКА",
        "resolve_busy": "ЗАКРОЙТЕ ПРОЕКТ RESOLVE",
        "log_title": "ЖУРНАЛ КОНВЕРТАЦИИ",
        "log_empty": "Здесь появятся этапы обработки проекта.",
        "log_read": "Читаю структуру Premiere…",
        "log_sequences": "Найдено секвенций: {count}",
        "log_convert": "Готовлю таймлайн «{name}» для Resolve…",
        "log_write": "Файл сохранён: {path}",
        "log_launch_resolve": "Запускаю DaVinci Resolve Studio…",
        "log_transfer_resolve": "Импортирую таймлайн и создаю DRP…",
        "log_done": "Готово. Проект передан в Resolve и сохранён как DRP.",
        "log_xml_done": "Готово. XML-файл сохранён.",
        "log_warning": "Внимание: {warning}",
        "log_error": "Не удалось обработать проект: {error}",
        "result": "Файл готов",
        "show_file": "Показать в папке",
        "again": "Выбрать другой проект",
        "handoff_title": "Автоматическая передача в Resolve Studio",
        "handoff_text": "Если Resolve не запущен, PR2DAVINCI откроет его. Для локальной передачи один раз включите внешнее scripting: Preferences → System → General → External scripting using → Local.",
        "supported": "Для передачи нужен DaVinci Resolve Studio с включённым внешним scripting. Если в Resolve открыт проект, PR2DAVINCI спросит разрешение сохранить его, временно закрыть и затем снова открыть. Эффекты и сложные элементы могут потребовать ручной настройки.",
        "switch_project_title": "В Resolve открыт проект",
        "switch_project_prompt": "Чтобы передать монтаж, PR2DAVINCI должен сохранить проект «{name}», временно закрыть его, создать DRP и затем снова открыть ваш проект. Продолжить?",
        "choose_file": "Выберите проект Premiere",
        "choose_filter": "Проекты Premiere (*.prproj);;Все файлы (*)",
        "choose_folder": "Папка для DRP",
        "choose_resolve": "Укажите исполняемый файл DaVinci Resolve Studio",
        "resolve_filter": "DaVinci Resolve (Resolve; Resolve.exe);;Все файлы (*)",
        "resolve_missing": "Не удалось определить путь к ResolvePython. Выберите исполняемый файл Resolve Studio — PR2DAVINCI попробует найти API рядом с ним.",
        "invalid_sequence": "В проекте не найдены секвенции.",
        "file_missing": "Файл проекта не найден.",
        "language": "Язык интерфейса",
    },
    "en": {
        "window": "Premiere → Resolve",
        "title": "Bring your edit into Resolve",
        "subtitle": "Choose a Premiere project and send the edit to DaVinci Resolve Studio.",
        "source": "PREMIERE PROJECT",
        "drop_title": "Drop a .prproj file here",
        "drop_hint": "or browse your computer",
        "choose": "Choose project",
        "change": "Change file",
        "sequence": "Sequence",
        "select_sequence": "Choose a sequence",
        "select_project_first": "Choose a Premiere project first",
        "output_placeholder": "DRP file name",
        "destination_placeholder": "Destination appears after project selection",
        "destination": "Save folder",
        "browse": "Browse",
        "output_name": "File name",
        "convert": "Send project to Resolve Studio",
        "export_xml": "Save XML",
        "export_fcpxml": "Save FCPXML",
        "busy": "Reading project…",
        "ready": "READY TO CONVERT",
        "idle": "WAITING FOR PROJECT",
        "working": "WORKING",
        "complete": "SENT TO RESOLVE",
        "complete_xml": "XML SAVED",
        "failed": "ERROR",
        "resolve_busy": "CLOSE RESOLVE PROJECT",
        "log_title": "CONVERSION LOG",
        "log_empty": "Project steps will appear here.",
        "log_read": "Reading Premiere structure…",
        "log_sequences": "Sequences found: {count}",
        "log_convert": "Preparing “{name}” for Resolve…",
        "log_write": "File saved: {path}",
        "log_launch_resolve": "Launching DaVinci Resolve Studio…",
        "log_transfer_resolve": "Importing the timeline and creating the DRP…",
        "log_done": "Done. The project was sent to Resolve and exported as a DRP.",
        "log_xml_done": "Done. The XML file has been saved.",
        "log_warning": "Attention: {warning}",
        "log_error": "Could not process the project: {error}",
        "result": "File ready",
        "show_file": "Show in folder",
        "again": "Choose another project",
        "handoff_title": "Automatic transfer to Resolve Studio",
        "handoff_text": "If Resolve is not running, PR2DAVINCI will launch it. Enable external scripting once in Preferences → System → General → External scripting using → Local.",
        "supported": "Transfer requires DaVinci Resolve Studio with external scripting enabled. If a project is open, PR2DAVINCI will ask before saving it, temporarily closing it, and reopening it. Effects and complex timeline elements may need manual adjustment.",
        "switch_project_title": "A Resolve project is open",
        "switch_project_prompt": "To send this edit, PR2DAVINCI must save “{name}”, temporarily close it, create the DRP, and then reopen your project. Continue?",
        "choose_file": "Choose a Premiere project",
        "choose_filter": "Premiere projects (*.prproj);;All files (*)",
        "choose_folder": "Choose DRP destination",
        "choose_resolve": "Select the DaVinci Resolve Studio executable",
        "resolve_filter": "DaVinci Resolve (Resolve; Resolve.exe);;All files (*)",
        "resolve_missing": "Could not locate ResolvePython. Select the Resolve Studio executable; PR2DAVINCI will look for the API runtime nearby.",
        "invalid_sequence": "No sequences were found in this project.",
        "file_missing": "Project file not found.",
        "language": "Interface language",
    },
}


class TaskThread(QThread):
    inspected = Signal(str, list)
    converted = Signal(str)
    failed = Signal(str)
    project_switch_required = Signal(str)
    log = Signal(str, object)

    def __init__(
        self,
        mode: str,
        source: Path,
        output: Path | None = None,
        sequence: str | None = None,
        sequence_index: int | None = None,
        resolve_installation: ResolveInstallation | None = None,
        native_project: bool = False,
        allow_project_switch: bool = False,
    ):
        super().__init__()
        self.mode = mode
        self.source = source
        self.native_project = False
        self.output = output
        self.sequence = sequence
        self.sequence_index = sequence_index
        self.resolve_installation = resolve_installation
        self.native_project = native_project
        self.allow_project_switch = allow_project_switch

    def run(self) -> None:
        try:
            if self.mode == "inspect":
                self.log.emit("log_read", {})
                entries = list_sequence_entries(self.source)
                self.inspected.emit(str(self.source), entries)
                return
            assert self.output is not None
            self.log.emit("log_convert", {"name": self.sequence or ""})
            if self.mode == "transfer":
                if self.resolve_installation is None:
                    raise ResolveTransferError("Не задан путь к DaVinci Resolve Studio.")
                with temporary_interchange_directory() as temporary_directory:
                    on_warning = lambda warning: self.log.emit("log_warning", {"warning": warning})
                    on_log = lambda key, values: self.log.emit(key, values)
                    if self.native_project:
                        manifest_path = Path(temporary_directory) / "timeline.json"
                        write_resolve_manifest(self.source, manifest_path, self.sequence_index, on_warning)
                        self.output = transfer_manifest_to_resolve(
                            manifest_path,
                            self.output,
                            self.resolve_installation,
                            on_log=on_log,
                            allow_project_switch=self.allow_project_switch,
                        )
                    else:
                        xml_path = Path(temporary_directory) / "timeline.xml"
                        convert_project(
                            self.source, xml_path, self.sequence, self.sequence_index,
                            on_warning=on_warning,
                            output_format="xmeml",
                        )
                        self.output = transfer_xml_to_resolve(
                            xml_path,
                            self.output,
                            self.resolve_installation,
                            on_log=on_log,
                            allow_project_switch=self.allow_project_switch,
                        )
            else:
                convert_project(
                    self.source, self.output, self.sequence, self.sequence_index,
                    on_warning=lambda warning: self.log.emit("log_warning", {"warning": warning}),
                )
            self.log.emit("log_write", {"path": str(self.output)})
            self.converted.emit(str(self.output))
        except ResolveProjectSwitchRequired as error:
            self.project_switch_required.emit(error.project_name)
        except Exception as error:
            self.failed.emit(str(error))


class BrandMark(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(42, 42)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#24a982"))
        painter.drawRoundedRect(0, 0, 42, 42, 13, 13)
        painter.setPen(QPen(Qt.GlobalColor.white, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawRoundedRect(11, 10, 18, 22, 3, 3)
        painter.drawLine(22, 10, 29, 17)
        painter.drawLine(22, 10, 22, 17)
        painter.setPen(QPen(Qt.GlobalColor.white, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(16, 24, 24, 24)
        painter.drawLine(20, 20, 20, 28)


class DropPanel(QFrame):
    file_dropped = Signal(str)

    def __init__(self, image_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropPanel")
        self.background_image = QPixmap(str(image_path))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.background_image.isNull():
            return
        area = QRectF(2, 2, 264, self.height() - 4)
        clip = QPainterPath()
        clip.addRoundedRect(area, 15, 15)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipPath(clip)
        source = self.background_image.scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter.setOpacity(0.76)
        painter.drawPixmap(area.toRect(), source, source.rect())
        painter.setOpacity(1.0)
        fade = QLinearGradient(area.topRight(), area.topLeft())
        fade.setColorAt(0.0, QColor(25, 30, 32, 255))
        fade.setColorAt(0.42, QColor(25, 30, 32, 224))
        fade.setColorAt(0.76, QColor(25, 30, 32, 155))
        fade.setColorAt(1.0, QColor(25, 30, 32, 128))
        painter.fillRect(area, fade)
        painter.end()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = [url for url in event.mimeData().urls() if url.isLocalFile()]
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Cutover", "PremiereToResolve")
        self.resolve_path = self.settings.value("resolve/executable", "")
        self.language = self.settings.value("language", "ru")
        if self.language not in TEXT:
            self.language = "ru"
        self.source: Path | None = None
        self.native_project = False
        self.output: Path | None = None
        self.task: TaskThread | None = None
        self._allow_project_switch = False
        self.error_message: str | None = None
        self.sequence_prompt = "select_project_first"
        self.logs: list[tuple[str, dict]] = []
        self.setWindowTitle(TEXT[self.language]["window"])
        icon_path = Path(__file__).resolve().parent / "assets" / "leonardo-icon-512.png"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(720, 650)
        self.resize(960, 1020)
        self.setAcceptDrops(True)
        self._build_ui()
        self._set_styles()
        self._bind_actions()
        self._translate()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        page = QVBoxLayout(root)
        page.setContentsMargins(54, 34, 54, 28)
        page.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)
        self.brand = BrandMark()
        self.brand.setObjectName("brand")
        header.addWidget(self.brand)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        self.brand_title = QLabel("PR2DAVINCI")
        self.brand_title.setObjectName("brandTitle")
        self.brand_subtitle = QLabel("PREMIERE PRO  /  DAVINCI RESOLVE")
        self.brand_subtitle.setObjectName("brandSubtitle")
        brand_text.addWidget(self.brand_title)
        brand_text.addWidget(self.brand_subtitle)
        header.addLayout(brand_text)
        header.addStretch(1)
        self.lang_ru = QToolButton()
        self.lang_ru.setText("RU")
        self.lang_en = QToolButton()
        self.lang_en.setText("EN")
        self.lang_ru.setCheckable(True)
        self.lang_en.setCheckable(True)
        self.lang_ru.setChecked(True)
        header.addWidget(self.lang_ru)
        header.addWidget(self.lang_en)
        page.addLayout(header)

        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setWordWrap(True)
        page.addWidget(self.title)
        page.addWidget(self.subtitle)

        self.drop_panel = DropPanel(Path(__file__).resolve().parent / "assets" / "leonardo-prime-minister.png")
        drop_layout = QVBoxLayout(self.drop_panel)
        drop_layout.setContentsMargins(26, 24, 26, 22)
        drop_layout.setSpacing(10)
        panel_heading = QHBoxLayout()
        self.source_caption = QLabel()
        self.source_caption.setObjectName("caption")
        self.state = QLabel()
        self.state.setObjectName("status")
        panel_heading.addWidget(self.source_caption)
        panel_heading.addStretch(1)
        panel_heading.addWidget(self.state)
        drop_layout.addLayout(panel_heading)

        self.drop_content = QWidget()
        drop_inner = QVBoxLayout(self.drop_content)
        drop_inner.setContentsMargins(4, 14, 4, 10)
        drop_inner.setSpacing(8)
        self.drop_title = QLabel()
        self.drop_title.setObjectName("dropTitle")
        self.drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_name = QLabel()
        self.file_name.setObjectName("fileName")
        self.file_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_name.setWordWrap(True)
        self.drop_hint = QLabel()
        self.drop_hint.setObjectName("muted")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.choose_button = QPushButton()
        self.choose_button.setObjectName("secondaryButton")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        drop_inner.addWidget(self.drop_title)
        drop_inner.addWidget(self.file_name)
        drop_inner.addWidget(self.drop_hint)
        drop_inner.addWidget(self.choose_button, 0, Qt.AlignmentFlag.AlignHCenter)
        drop_layout.addWidget(self.drop_content, 1)
        page.addWidget(self.drop_panel)

        options = QHBoxLayout()
        options.setSpacing(14)
        sequence_box = QVBoxLayout()
        sequence_box.setSpacing(7)
        self.sequence_label = QLabel()
        self.sequence_label.setObjectName("fieldLabel")
        self.sequence = QComboBox()
        self.sequence.setObjectName("field")
        self.sequence.setMinimumHeight(44)
        self.sequence.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.sequence.setMaxVisibleItems(12)
        self.sequence.addItem(self.tr("select_project_first"))
        self.sequence.setEnabled(False)
        self.sequence_progress_page = QWidget()
        progress_layout = QGridLayout(self.sequence_progress_page)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.sequence_progress = QProgressBar()
        self.sequence_progress.setObjectName("sequenceProgress")
        self.sequence_progress.setRange(0, 0)
        self.sequence_progress.setTextVisible(False)
        self.sequence_progress.setMinimumHeight(44)
        self.sequence_progress_label = QLabel(self.tr("busy"))
        self.sequence_progress_label.setObjectName("sequenceProgressLabel")
        self.sequence_progress_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        progress_layout.addWidget(self.sequence_progress, 0, 0)
        progress_layout.addWidget(self.sequence_progress_label, 0, 0)
        self.sequence_controls = QStackedWidget()
        self.sequence_controls.setMinimumHeight(44)
        self.sequence_controls.addWidget(self.sequence)
        self.sequence_controls.addWidget(self.sequence_progress_page)
        sequence_box.addWidget(self.sequence_label)
        sequence_box.addWidget(self.sequence_controls)
        options.addLayout(sequence_box, 1)

        output_box = QVBoxLayout()
        output_box.setSpacing(7)
        self.destination_label = QLabel()
        self.destination_label.setObjectName("fieldLabel")
        destination_row = QHBoxLayout()
        destination_row.setSpacing(8)
        self.destination = QLineEdit()
        self.destination.setObjectName("field")
        self.destination.setMinimumHeight(44)
        self.destination.setReadOnly(True)
        self.browse_button = QPushButton()
        self.browse_button.setObjectName("browseButton")
        self.browse_button.setMinimumHeight(44)
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(self.browse_button)
        output_box.addWidget(self.destination_label)
        output_box.addLayout(destination_row)
        options.addLayout(output_box, 1)
        page.addLayout(options)

        self.output_name_label = QLabel()
        self.output_name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit()
        self.output_name.setObjectName("field")
        self.output_name.setMinimumHeight(42)
        self.output_name.setPlaceholderText(self.tr("output_placeholder"))
        page.addWidget(self.output_name_label)
        page.addWidget(self.output_name)

        action_row = QHBoxLayout()
        action_row.setSpacing(12)
        self.convert_button = QPushButton()
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.setMinimumHeight(50)
        self.convert_button.setEnabled(False)
        self.export_xml_button = QPushButton()
        self.export_xml_button.setObjectName("secondaryButton")
        self.export_xml_button.setMinimumHeight(50)
        self.export_xml_button.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setObjectName("progress")
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(110)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        action_row.addWidget(self.convert_button, 0, Qt.AlignmentFlag.AlignLeft)
        action_row.addWidget(self.export_xml_button, 0, Qt.AlignmentFlag.AlignLeft)
        action_row.addWidget(self.progress, 0, Qt.AlignmentFlag.AlignVCenter)
        action_row.addStretch(1)
        page.addLayout(action_row)

        log_frame = QFrame()
        log_frame.setObjectName("logFrame")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(18, 15, 18, 16)
        log_layout.setSpacing(10)
        log_head = QHBoxLayout()
        self.log_title = QLabel()
        self.log_title.setObjectName("caption")
        log_head.addWidget(self.log_title)
        log_head.addStretch(1)
        log_layout.addLayout(log_head)
        self.log_output = QLabel()
        self.log_output.setObjectName("logOutput")
        self.log_output.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.log_output.setWordWrap(True)
        self.log_output.setMinimumHeight(82)
        log_layout.addWidget(self.log_output)
        self.result_row = QHBoxLayout()
        self.result = QLabel()
        self.result.setObjectName("resultLabel")
        self.show_file_button = QPushButton()
        self.show_file_button.setObjectName("reportButton")
        self.show_file_button.setEnabled(False)
        self.show_file_button.hide()
        self.result_row.addWidget(self.result, 1)
        self.result_row.addWidget(self.show_file_button)
        log_layout.addLayout(self.result_row)
        page.addWidget(log_frame, 1)

        handoff = QFrame()
        handoff.setObjectName("handoff")
        handoff_layout = QHBoxLayout(handoff)
        handoff_layout.setContentsMargins(18, 14, 18, 14)
        handoff_layout.setSpacing(14)
        self.handoff_mark = QLabel("→")
        self.handoff_mark.setObjectName("handoffMark")
        handoff_layout.addWidget(self.handoff_mark, 0, Qt.AlignmentFlag.AlignTop)
        handoff_copy = QVBoxLayout()
        handoff_copy.setSpacing(4)
        self.handoff_title = QLabel()
        self.handoff_title.setObjectName("handoffTitle")
        self.handoff_text = QLabel()
        self.handoff_text.setObjectName("handoffText")
        self.handoff_text.setWordWrap(True)
        handoff_copy.addWidget(self.handoff_title)
        handoff_copy.addWidget(self.handoff_text)
        handoff_layout.addLayout(handoff_copy, 1)
        page.addWidget(handoff)

        self.support_note = QLabel()
        self.support_note.setObjectName("supportNote")
        self.support_note.setWordWrap(True)
        page.addWidget(self.support_note)

    def _set_styles(self) -> None:
        self.setStyleSheet("""
            QWidget#root { background-color: #111416; color: #edf1ef; }
            QLabel { background: transparent; }
            QLabel#brandTitle { color: #f1f4f2; font-size: 13px; font-weight: 800; letter-spacing: 2px; }
            QLabel#brandSubtitle, QLabel#caption { color: #94a09b; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
            QLabel#pageTitle { color: #f2f5f3; font-size: 29px; font-weight: 700; }
            QLabel#pageSubtitle { color: #a4afaa; font-size: 13px; }
            QWidget#brand { background: #24a982; border-radius: 13px; }
            QToolButton { color: #82908a; background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 7px 9px; font-size: 10px; font-weight: 700; }
            QToolButton:checked { color: #d9fff0; background: #1e302a; border-color: #315344; }
            QFrame#dropPanel { background: #191e20; border: 1px dashed #40504a; border-radius: 18px; }
            QFrame#dropPanel:hover { border-color: #35bf96; }
            QLabel#status { color: #78ddb8; background: #1b332b; border-radius: 9px; padding: 6px 9px; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
            QLabel#dropTitle { color: #edf3ef; font-size: 17px; font-weight: 650; }
            QLabel#fileName { color: #65d8b1; font-size: 13px; font-weight: 600; }
            QLabel#muted { color: #87938d; font-size: 12px; }
            QPushButton#secondaryButton { color: #b6d4ff; background: #202b3b; border: 1px solid #2d4668; border-radius: 9px; padding: 10px 19px; font-size: 12px; font-weight: 650; }
            QPushButton#secondaryButton:hover, QPushButton#browseButton:hover, QPushButton#reportButton:hover { background: #29384a; }
            QLabel#fieldLabel { color: #a0aaa5; font-size: 11px; font-weight: 650; }
            QComboBox#field, QLineEdit#field { color: #e8efeb; background: #191e20; border: 1px solid #343d39; border-radius: 9px; padding: 0 12px; font-size: 12px; selection-background-color: #257f66; }
            QComboBox#field:focus, QLineEdit#field:focus { border-color: #39bd93; }
            QComboBox#field:disabled { color: #66716c; }
            QComboBox#field::drop-down { width: 30px; border: 0; }
            QComboBox QAbstractItemView { color: #e8efeb; background: #202628; selection-background-color: #266f59; border: 1px solid #38433e; padding: 5px; }
            QPushButton#browseButton { color: #d4ddd8; background: #242a2b; border: 1px solid #3a4340; border-radius: 9px; padding: 0 15px; font-size: 11px; font-weight: 600; }
            QPushButton#primaryButton { color: #071a13; background: #43c69a; border: 1px solid #43c69a; border-radius: 10px; padding: 0 21px; font-size: 13px; font-weight: 750; }
            QPushButton#primaryButton:hover:enabled { background: #61d8ae; border-color: #61d8ae; }
            QPushButton#primaryButton:disabled { color: #697771; background: #28312d; border-color: #303b35; }
            QProgressBar#progress { background: #2a3330; border: 0; border-radius: 2px; }
            QProgressBar#progress::chunk { background: #43c69a; border-radius: 2px; }
            QProgressBar#sequenceProgress { color: #d5e7df; background: #191e20; border: 1px solid #343d39; border-radius: 9px; padding: 0 12px; text-align: left; font-size: 12px; }
            QProgressBar#sequenceProgress::chunk { background: #1e302a; border: 0; border-radius: 8px; }
            QLabel#sequenceProgressLabel { color: #d5e7df; background: transparent; padding: 0 12px; font-size: 12px; }
            QScrollBar:vertical { background: #111416; width: 8px; margin: 2px 2px 2px 0; }
            QScrollBar::handle:vertical { background: #35403a; border-radius: 4px; min-height: 28px; }
            QScrollBar::handle:vertical:hover { background: #52615a; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QFrame#logFrame { background: #15191a; border: 1px solid #29302e; border-radius: 13px; }
            QLabel#logOutput { color: #aab3ae; font-family: 'SFMono-Regular', 'Cascadia Code', 'DejaVu Sans Mono', monospace; font-size: 11px; line-height: 1.6; }
            QLabel#resultLabel { color: #78847e; font-size: 11px; }
            QPushButton#reportButton { color: #d1a34e; background: #28251e; border: 1px solid #51432a; border-radius: 8px; padding: 9px 13px; font-size: 11px; font-weight: 650; }
            QPushButton#reportButton:disabled { color: #706951; background: #211f1a; border-color: #353026; }
            QFrame#handoff { background: #18221f; border: 1px solid #293c34; border-radius: 12px; }
            QLabel#handoffMark { color: #4bc99d; font-size: 19px; font-weight: 700; }
            QLabel#handoffTitle { color: #c5dcd2; font-size: 11px; font-weight: 700; }
            QLabel#handoffText { color: #98aaa1; font-size: 11px; }
            QLabel#supportNote { color: #707b75; font-size: 10px; }
            QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus { outline: none; }
        """)

    def _bind_actions(self) -> None:
        self.lang_ru.clicked.connect(lambda: self.set_language("ru"))
        self.lang_en.clicked.connect(lambda: self.set_language("en"))
        self.choose_button.clicked.connect(self.choose_source)
        self.drop_panel.file_dropped.connect(self.load_source)
        self.browse_button.clicked.connect(self.choose_destination)
        self.convert_button.clicked.connect(self.start_conversion)
        self.export_xml_button.clicked.connect(self.start_xml_export)
        self.show_file_button.clicked.connect(self.show_output)
        self.sequence.currentIndexChanged.connect(self._update_convert_enabled)
        open_action = QAction(self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.choose_source)
        self.addAction(open_action)
        convert_action = QAction(self)
        convert_action.setShortcut("Ctrl+Return")
        convert_action.triggered.connect(self.start_conversion)
        self.addAction(convert_action)

    def tr(self, key: str, **values) -> str:
        return TEXT[self.language][key].format(**values)

    def _translate(self) -> None:
        self.setWindowTitle(self.tr("window"))
        self.title.setText(self.tr("title"))
        self.subtitle.setText(self.tr("subtitle"))
        self.source_caption.setText(self.tr("source"))
        self.drop_title.setText(self.tr("drop_title"))
        self.drop_hint.setText(self.tr("drop_hint") if self.source is None else self.tr("change"))
        self.choose_button.setText(self.tr("choose") if self.source is None else self.tr("change"))
        self.sequence_label.setText(self.tr("sequence"))
        self.sequence_progress_label.setText(self.tr("busy"))
        self.destination_label.setText(self.tr("destination"))
        self.destination.setPlaceholderText(self.tr("destination_placeholder"))
        self.output_name.setPlaceholderText(self.tr("output_placeholder"))
        self.browse_button.setText(self.tr("browse"))
        self.output_name_label.setText(self.tr("output_name"))
        self.convert_button.setText(self.tr("convert"))
        self.export_xml_button.setText(self.tr("export_fcpxml" if self.native_project else "export_xml"))
        self.log_title.setText(self.tr("log_title"))
        self.handoff_title.setText(self.tr("handoff_title"))
        self.handoff_text.setText(self.tr("handoff_text"))
        self.support_note.setText(self.tr("supported"))
        self.lang_ru.setChecked(self.language == "ru")
        self.lang_en.setChecked(self.language == "en")
        if self.sequence.count():
            self.sequence.setItemText(0, self.tr(self.sequence_prompt))
        self._render_state()
        self._render_logs()
        if not self.logs and self.source is None:
            self.log_output.setText(self.tr("log_empty"))
        self.result.setText(self.tr("result") if self.output and self.output.exists() else "")
        self.show_file_button.setText(self.tr("show_file"))

    def set_language(self, language: str) -> None:
        self.language = language
        self.settings.setValue("language", language)
        self._translate()

    def _render_state(self) -> None:
        if self.task is not None and self.task.isRunning():
            key = "working" if self.task.mode in {"convert", "transfer"} else "busy"
        elif self.error_message:
            key = "resolve_busy" if "В Resolve открыт проект" in self.error_message else "failed"
        elif self.output is not None and self.output.exists():
            key = "complete_xml" if self.output.suffix.lower() in {".xml", ".fcpxml"} else "complete"
        elif self.source is not None:
            key = "ready"
        else:
            key = "idle"
        self.state.setText(self.tr(key))

    def _render_logs(self) -> None:
        if not self.logs:
            return
        rendered = []
        for key, values in self.logs[-6:]:
            rendered.append("› " + self.tr(key, **values))
        self.log_output.setText("\n".join(rendered))

    def _append_log(self, key: str, values: dict | None = None) -> None:
        self.logs.append((key, values or {}))
        self._render_logs()

    def choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("choose_file"), "", self.tr("choose_filter"))
        if path:
            self.load_source(path)

    def choose_destination(self) -> None:
        start = str(self.source.parent) if self.source else ""
        folder = QFileDialog.getExistingDirectory(self, self.tr("choose_folder"), start)
        if folder:
            self.destination.setText(folder)

    def load_source(self, path_text: str) -> None:
        source = Path(path_text)
        if not source.is_file():
            QMessageBox.warning(self, self.tr("window"), self.tr("file_missing"))
            return
        self.source = source
        self.output = None
        self.error_message = None
        self.state.setStyleSheet("")
        self.result.setText("")
        self.result.setStyleSheet("")
        self.show_file_button.hide()
        self.show_file_button.setEnabled(False)
        self.sequence.clear()
        self.sequence_prompt = "busy"
        self.sequence.addItem(self.tr("busy"))
        self.sequence.setEnabled(False)
        self.sequence_progress_label.setText(self.tr("busy"))
        self.sequence_controls.setCurrentWidget(self.sequence_progress_page)
        self.destination.setText(str(source.parent))
        self.output_name.setText(source.stem + "_Resolve.drp")
        self.file_name.setText(source.name)
        self.choose_button.setText(self.tr("change"))
        self.drop_hint.setText(str(source.parent))
        self.show_file_button.setEnabled(False)
        self.logs.clear()
        self._append_log("log_read")
        self._render_state()
        self._start_task(TaskThread("inspect", source))

    def _start_task(self, task: TaskThread) -> None:
        self.task = task
        task.log.connect(self._append_log)
        task.inspected.connect(self._on_inspected)
        task.converted.connect(self._on_converted)
        task.failed.connect(self._on_failed)
        task.project_switch_required.connect(self._on_project_switch_required)
        task.finished.connect(self._on_task_finished)
        task.start()
        self._render_state()
        self._update_convert_enabled()

    def _on_inspected(self, path: str, entries: list[SequenceEntry]) -> None:
        if self.source is None or Path(path) != self.source:
            return
        self.sequence.clear()
        self.native_project = bool(entries and entries[0].native)
        self.sequence_controls.setCurrentWidget(self.sequence)
        if not entries:
            self.sequence_prompt = "invalid_sequence"
            self.sequence.addItem(self.tr(self.sequence_prompt))
            self.error_message = self.tr("invalid_sequence")
            self.state.setStyleSheet("color: #f3b58c; background: #3b2922; border-radius: 9px; padding: 6px 9px; font-size: 9px; font-weight: 800; letter-spacing: 1px;")
            self._append_log("log_error", {"error": self.tr("invalid_sequence")})
            self._render_state()
            return
        self.sequence_prompt = "select_sequence"
        self.sequence.addItem(self.tr(self.sequence_prompt))
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.name] = counts.get(entry.name, 0) + 1
        for entry in entries:
            label = entry.name
            if counts[entry.name] > 1:
                label = f"{entry.name} · ID {entry.premiere_id}"
            self.sequence.addItem(label, entry.index)
        self.sequence.setCurrentIndex(0)
        self.sequence.setEnabled(True)
        self._append_log("log_sequences", {"count": len(entries)})
        self.export_xml_button.setText(self.tr("export_fcpxml" if self.native_project else "export_xml"))
        self.log_output.setMinimumHeight(min(146, 60 + 19 * min(len(entries), 4)))

    def _on_converted(self, path: str) -> None:
        self.output = Path(path)
        self._append_log("log_xml_done" if self.output.suffix.lower() in {".xml", ".fcpxml"} else "log_done")
        self.result.setText(self.tr("result"))
        self.result.setStyleSheet("color: #70d8ae; font-weight: 650;")
        self.show_file_button.setEnabled(True)
        self.show_file_button.show()

    def _on_failed(self, error: str) -> None:
        self.sequence_controls.setCurrentWidget(self.sequence)
        self.error_message = error
        self.state.setText(self.tr("failed"))
        self.state.setStyleSheet("color: #f3b58c; background: #3b2922; border-radius: 9px; padding: 6px 9px; font-size: 9px; font-weight: 800; letter-spacing: 1px;")
        self._append_log("log_error", {"error": error})
        self.result.setText(error)
        self.result.setStyleSheet("color: #efad8d;")
        self.show_file_button.hide()

    def _on_project_switch_required(self, project_name: str) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("switch_project_title"),
            self.tr("switch_project_prompt", name=project_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._allow_project_switch = True
            QTimer.singleShot(100, self.start_conversion)
        else:
            self.error_message = None
            cancelled = "Передача отменена." if self.language == "ru" else "Transfer cancelled."
            self._append_log("log_warning", {"warning": cancelled})

    def _on_task_finished(self) -> None:
        task = self.sender()
        if task is self.task:
            self.task = None
        if task is not None:
            task.deleteLater()
        self.progress.hide()
        self._render_state()
        self._update_convert_enabled()

    def _update_convert_enabled(self, *_args) -> None:
        busy = self.task is not None and self.task.isRunning()
        has_selection = self.source is not None and self.sequence.currentData() is not None and self.sequence.isEnabled()
        self.convert_button.setEnabled(bool(has_selection and not busy))
        self.export_xml_button.setEnabled(bool(has_selection and not busy))
        self.choose_button.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)

    def start_conversion(self) -> None:
        if self.source is None or self.sequence.currentData() is None:
            return
        installation = installation_from_path(self.resolve_path) if self.resolve_path else None
        if installation is None:
            installation = find_resolve_installation()
        if installation is None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("choose_resolve"),
                "",
                self.tr("resolve_filter"),
            )
            if not path:
                return
            installation = installation_from_path(path)
            if installation is None:
                QMessageBox.warning(self, self.tr("window"), self.tr("resolve_missing"))
                return
            self.resolve_path = path
            self.settings.setValue("resolve/executable", path)
        output = self._output_path(".drp")
        self.output = None
        self.error_message = None
        self.result.setText("")
        self.result.setStyleSheet("")
        self.show_file_button.hide()
        self.state.setStyleSheet("")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.logs.clear()
        self._start_task(TaskThread(
            "transfer", self.source, output,
            sequence=self.sequence.currentText(),
            sequence_index=self.sequence.currentData(),
            resolve_installation=installation,
            native_project=self.native_project,
            allow_project_switch=self._allow_project_switch,
        ))
        self._allow_project_switch = False

    def start_xml_export(self) -> None:
        if self.source is None or self.sequence.currentData() is None:
            return
        output = self._output_path(".fcpxml" if self.native_project else ".xml")
        self.output = None
        self.error_message = None
        self.result.setText("")
        self.result.setStyleSheet("")
        self.show_file_button.hide()
        self.state.setStyleSheet("")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.logs.clear()
        self._start_task(TaskThread(
            "convert", self.source, output,
            sequence=self.sequence.currentText(),
            sequence_index=self.sequence.currentData(),
        ))

    def _output_path(self, extension: str) -> Path:
        assert self.source is not None
        folder = Path(self.destination.text().strip() or str(self.source.parent))
        name = self.output_name.text().strip() or (self.source.stem + "_Resolve" + extension)
        if Path(name).suffix.lower() in {".drp", ".xml", ".fcpxml"}:
            name = str(Path(name).with_suffix(extension))
        else:
            name += extension
        self.output_name.setText(name)
        return folder / name

    def show_output(self) -> None:
        if self.output is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output.parent)))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = [url for url in event.mimeData().urls() if url.isLocalFile()]
        if urls:
            self.load_source(urls[0].toLocalFile())
            event.acceptProposedAction()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Premiere to Resolve")
    app.setOrganizationName("Cutover")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
