from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MAX_PIXELS = 1_000_000
MAX_DPI = 100_000
RUN_HINT = "Add source files, an export format and an output folder first"


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    return widget


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("role", "separator")
    line.setFixedHeight(1)
    return line


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sources: list[Path] = []
        self.results: list[str] = []
        self.total = 0
        self.output_dir = ""
        self.message = ""
        self.loading = False

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(8)
        content_layout.addLayout(self.build_header())

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def build_header(self) -> QHBoxLayout:

        self.run_button = QPushButton("Run Batch")
        self.run_button.setProperty("role", "accent")

        header = QHBoxLayout()
        header.setSpacing(8)
        for widget in (self.run_button,):
            header.addWidget(widget)
        header.addStretch()
        return header

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.add_dropped(Path(url.toLocalFile()))
        event.acceptProposedAction()
        self.refresh_sources()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker:
            self.worker.requestInterruption()
            self.worker.wait()
        event.accept()
