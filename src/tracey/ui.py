import re
import sys
from dataclasses import dataclass
from enum import Enum
from itertools import count
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QImageReader,
    QKeySequence,
    QMouseEvent,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tracey import APP_NAME, APP_VERSION, theme
from tracey.app import (
    CLIPPING_PATH_NAME,
    load_mask,
    trace_mask,
    write_svg,
    write_tiff,
)

IMAGE_EXTENSIONS = {".png", ".tif", ".tiff"}
IMAGE_FILTER = "Images (*.png *.tif *.tiff)"
MASK_WORDS = re.compile(r"(alpha|mask|matte)", re.IGNORECASE)
RUN_HINT = "Add at least one job to the queue first"


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def natural_key(path: Path) -> list[int | str]:
    """Sort shot_2 before shot_10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


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


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Status(Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class Job:
    id: int
    mask: Path
    beauty: Path | None
    output: Path
    alphamax: float
    turdsize: int
    offset: float
    threshold: float
    tolerance: float
    clipping: bool
    invert: bool
    svg: bool
    status: Status = Status.PENDING
    progress: int = 0
    message: str = ""


class BatchWorker(QThread):
    job_progress = Signal(int, int, str)  # job id, percent, stage
    job_finished = Signal(int, object, str)  # job id, Status, message

    def __init__(self, jobs: list[Job]) -> None:
        super().__init__()
        self.jobs = jobs

    def run(self) -> None:
        for job in self.jobs:
            if self.isInterruptionRequested():
                self.job_finished.emit(job.id, Status.PENDING, "")
                continue
            try:
                message = self.process(job)
            except InterruptedError:
                self.job_finished.emit(job.id, Status.CANCELLED, "Cancelled")
            except Exception as error:  # noqa: BLE001 - report on the job, keep going
                self.job_finished.emit(job.id, Status.FAILED, str(error) or repr(error))
            else:
                self.job_finished.emit(job.id, Status.DONE, message)

    def process(self, job: Job) -> str:
        last = -1

        def report(percent: float, stage: str) -> None:
            nonlocal last
            if int(percent) != last:
                last = int(percent)
                self.job_progress.emit(job.id, last, stage)

        report(0, "Loading")
        mask_image = Image.open(job.mask)
        mask_image.load()
        mask = load_mask(mask_image, job.invert, job.threshold)
        if not mask.any():
            raise ValueError("The mask is empty, nothing to trace")

        image = mask_image
        if job.beauty:
            image = Image.open(job.beauty)
            image.load()
            (bw, bh), (mw, mh) = image.size, mask_image.size
            if abs(bw / bh - mw / mh) > 0.01:
                raise ValueError(
                    f"Beauty ({bw}×{bh}) and mask ({mw}×{mh}) aspect ratios differ"
                )

        report(5, "Tracing")
        plist = trace_mask(
            mask,
            alphamax=job.alphamax,
            turdsize=job.turdsize,
            tolerance=job.tolerance,
            progress=lambda f: report(5 + 85 * f, "Tracing"),
            cancelled=self.isInterruptionRequested,
        )
        if not plist:
            raise ValueError("No shape survived tracing, try a smaller speckle size")

        report(90, "Writing")
        job.output.parent.mkdir(parents=True, exist_ok=True)
        write_tiff(
            image,
            plist,
            str(job.output),
            size=mask_image.size,
            offset=job.offset,
            clipping=job.clipping,
        )
        if job.svg:
            svg = str(job.output.with_suffix(".svg"))
            write_svg(mask_image, plist, svg, offset=job.offset)
        report(100, "Done")
        return f"{len(plist)} paths"


class DropField(QFrame):
    """A drop target for one or more images, with a thumbnail of the first."""

    changed = Signal()

    def __init__(self, title: str, required: bool) -> None:
        super().__init__()
        self.title = title
        self.files: list[Path] = []
        self.setProperty("role", "dropfield")
        self.setAcceptDrops(True)
        self.setMinimumHeight(118)

        browse = QPushButton("Browse…")
        browse.setProperty("role", "ghost")
        browse.clicked.connect(self.browse)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("role", "ghost")
        self.clear_button.clicked.connect(lambda: self.set_files([]))

        top = QHBoxLayout()
        top.addWidget(label(title, "fieldtitle"))
        top.addWidget(
            label(
                "required" if required else "optional",
                "required" if required else "optional",
            )
        )
        top.addStretch()
        top.addWidget(browse)
        top.addWidget(self.clear_button)

        self.thumbnail = QLabel()
        self.thumbnail.setProperty("role", "thumbnail")
        self.thumbnail.setFixedSize(72, 72)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary = label("", "muted")
        self.summary.setWordWrap(True)

        body = QHBoxLayout()
        body.addWidget(self.thumbnail)
        body.addWidget(self.summary, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.addLayout(top)
        layout.addLayout(body)
        self.refresh()

    def set_files(self, files: list[Path]) -> None:
        self.files = sorted(dict.fromkeys(files), key=natural_key)
        self.refresh()
        self.changed.emit()

    def browse(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, f"Choose {self.title.lower()}", "", IMAGE_FILTER
        )
        if names:
            self.set_files([Path(n) for n in names])

    def refresh(self) -> None:
        self.clear_button.setEnabled(bool(self.files))
        self.thumbnail.setPixmap(QPixmap())
        if not self.files:
            self.thumbnail.setText("＋")
            self.summary.setText(
                "Drop TIFF / PNG files here, or double-click to browse"
            )
            return

        self.thumbnail.setText("")
        reader = QImageReader(str(self.files[0]))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(
                size.scaled(QSize(72, 72), Qt.AspectRatioMode.KeepAspectRatio)
            )
        image = reader.read()
        if image.isNull():
            self.thumbnail.setText("?")
        else:
            self.thumbnail.setPixmap(QPixmap.fromImage(image))

        names = [f.name for f in self.files[:3]]
        if len(self.files) > 3:
            names.append(f"… and {len(self.files) - 3} more")
        self.summary.setText(
            f"<b>{len(self.files)} file{'s' * (len(self.files) != 1)}</b><br>"
            + "<br>".join(names)
        )

    def set_hover(self, hover: bool) -> None:
        self.setProperty("hover", hover)
        repolish(self)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.browse()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(
            is_image(Path(u.toLocalFile()))
            for u in event.mimeData().urls()
            if u.isLocalFile()
        ):
            event.acceptProposedAction()
            self.set_hover(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.set_hover(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self.set_hover(False)
        paths = [
            Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()
        ]
        self.set_files([p for p in paths if is_image(p)])
        event.acceptProposedAction()


STATUS_COLORS = {
    Status.PENDING: "muted",
    Status.RUNNING: "accent",
    Status.DONE: "success",
    Status.FAILED: "danger",
    Status.CANCELLED: "muted",
}


class QueueTable(QTableWidget):
    COLUMNS = ("Beauty", "Mask", "α", "Offset", "Status", "Progress")
    STATUS, PROGRESS = 4, 5

    def __init__(self) -> None:
        super().__init__(0, len(self.COLUMNS))
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(40)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in ((2, 52), (3, 76), (4, 220), (5, 150)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, width)

    def cell(self, row: int, column: int) -> QTableWidgetItem:
        item = self.item(row, column)
        assert item is not None  # add_job fills every text column
        return item

    def job_id(self, row: int) -> int:
        return self.cell(row, 0).data(Qt.ItemDataRole.UserRole)

    def row_of(self, job_id: int) -> int:
        for row in range(self.rowCount()):
            if self.job_id(row) == job_id:
                return row
        return -1

    def add_job(self, job: Job) -> None:
        row = self.rowCount()
        self.insertRow(row)
        beauty = QTableWidgetItem(job.beauty.name if job.beauty else "—")
        beauty.setData(Qt.ItemDataRole.UserRole, job.id)
        beauty.setToolTip(
            str(job.beauty)
            if job.beauty
            else "No beauty, the path is saved into the mask"
        )
        mask = QTableWidgetItem(job.mask.name)
        mask.setToolTip(str(job.mask))
        alpha = QTableWidgetItem(f"{job.alphamax:g}")
        alpha.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        alpha.setToolTip(
            f"Threshold {job.threshold:.0%} · smoothness {job.alphamax:g}"
            f" · simplify {job.tolerance:g} · speckles {job.turdsize} px"
            + (" · clipping path" if job.clipping else "")
            + (" · inverted" if job.invert else "")
        )
        self.setItem(row, 0, beauty)
        self.setItem(row, 1, mask)
        self.setItem(row, 2, alpha)
        offset = QTableWidgetItem(f"{job.offset:+g} px" if job.offset else "—")
        offset.setToolTip("Grown outwards" if job.offset > 0 else "Shrunk inwards")
        self.setItem(row, 3, offset)
        self.setItem(row, self.STATUS, QTableWidgetItem())
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        container = QWidget()
        inner = QHBoxLayout(container)
        inner.setContentsMargins(8, 0, 8, 0)
        inner.addWidget(bar)
        self.setCellWidget(row, self.PROGRESS, container)
        self.update_job(job)

    def update_job(self, job: Job, stage: str = "") -> None:
        row = self.row_of(job.id)
        if row < 0:
            return
        status = self.cell(row, self.STATUS)
        text = job.status.value
        if job.status is Status.RUNNING and stage:
            text = f"{stage} · {job.progress}%"
        elif job.message:
            text = f"{text} · {job.message}"
        status.setText(text)
        status.setToolTip(
            f"{job.message}\n→ {job.output}" if job.message else f"→ {job.output}"
        )
        status.setData(Qt.ItemDataRole.UserRole, job.status.name.lower())
        status.setForeground(theme.color(STATUS_COLORS[job.status]))
        bar = self.cellWidget(row, self.PROGRESS).findChild(QProgressBar)
        assert bar is not None  # every row gets one in add_job
        bar.setValue(job.progress)
        bar.setProperty("status", job.status.name.lower())
        repolish(bar)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[Job] = []
        self.run_ids: list[int] = []
        self.worker: BatchWorker | None = None
        self.cancelling = False
        self.ids = count(1)

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, self.remove_selected)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(self.build_inputs())
        splitter.addWidget(self.build_queue())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 880])

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.addWidget(splitter, 1)

        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.build_header())
        root_layout.addWidget(content, 1)
        root_layout.addWidget(self.build_footer())
        self.setCentralWidget(root)

        self.refresh_sources()
        self.refresh_queue()
        QApplication.styleHints().colorSchemeChanged.connect(self.refresh_theme)

    def build_header(self) -> QFrame:
        self.run_button = QPushButton("Run Batch")
        self.run_button.setProperty("role", "accent")
        self.run_button.clicked.connect(self.run_batch)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.clicked.connect(self.cancel_batch)

        logo = QLabel()
        logo.setPixmap(theme.logo(32, self.devicePixelRatioF()))

        header = QFrame()
        header.setProperty("role", "topbar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)
        layout.addWidget(logo)
        layout.addWidget(label(f"{APP_NAME} - {APP_VERSION}", "apptitle"))
        layout.addStretch()
        for widget in (self.cancel_button, self.run_button):
            layout.addWidget(widget)
        return header

    def build_inputs(self) -> QWidget:
        self.beauty_field = DropField("Beauty render", required=False)
        self.mask_field = DropField("Alpha mask   ", required=True)
        for field in (self.beauty_field, self.mask_field):
            field.changed.connect(self.refresh_sources)

        self.alphamax = QDoubleSpinBox()
        self.alphamax.setRange(0, 1.34)
        self.alphamax.setSingleStep(0.05)
        self.alphamax.setValue(0.5)
        self.alphamax.setToolTip(
            "Corner threshold: 0 gives a polygon, higher values smoother curves"
        )
        self.turdsize = QSpinBox()
        self.turdsize.setRange(0, 10_000)
        self.turdsize.setValue(2)
        self.turdsize.setSuffix(" px")
        self.turdsize.setToolTip("Specks up to this area are ignored")
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-25, 25)
        self.offset.setDecimals(2)
        self.offset.setSingleStep(0.25)
        self.offset.setSuffix(" px")
        self.offset.setToolTip(
            "Moves the path outwards (positive) or inwards (negative), in mask"
            " pixels.\nKeep shrinking below the radius of the tightest curve."
        )
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 99)
        self.threshold.setValue(50)
        self.threshold.setSuffix(" %")
        self.threshold.setToolTip(
            "Mask value at which a pixel counts as inside. On soft edges, lower"
            " values move the path outwards, higher ones inwards."
        )
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0, 1)
        self.tolerance.setDecimals(2)
        self.tolerance.setSingleStep(0.05)
        self.tolerance.setValue(0.2)
        self.tolerance.setToolTip(
            "How far joined curves may stray from the mask: higher values give"
            " fewer anchor points, 0 keeps every segment."
        )
        self.invert = QCheckBox("Invert mask")
        self.clipping = QCheckBox("Mark as clipping path")
        self.clipping.setToolTip(
            f'Saves the path as "{CLIPPING_PATH_NAME}" and makes it the clipping'
            " path of the image, so layout apps cut the image out."
        )
        self.svg = QCheckBox("Also write an SVG")

        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("Next to the source files")
        output_browse = QPushButton("…")
        output_browse.setProperty("role", "square")
        output_browse.setFixedWidth(34)
        output_browse.clicked.connect(self.browse_output)
        output = QHBoxLayout()
        output.addWidget(self.output_dir, 1)
        output.addWidget(output_browse)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Threshold", self.threshold)
        form.addRow("Smoothness", self.alphamax)
        form.addRow("Simplify", self.tolerance)
        form.addRow("Speckle size", self.turdsize)
        form.addRow("Grow / shrink", self.offset)
        form.addRow("", self.invert)
        form.addRow("", self.clipping)
        form.addRow("", self.svg)
        form.addRow("Output folder", output)

        self.pairing = label("", "muted")
        self.pairing.setWordWrap(True)
        self.add_button = QPushButton("Add to Queue")
        self.add_button.setProperty("role", "accent")
        self.add_button.clicked.connect(self.add_jobs)

        panel = QFrame()
        panel.setProperty("role", "card")
        panel.setMinimumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(label("New job", "section"))
        layout.addWidget(self.beauty_field)
        layout.addWidget(self.mask_field)
        layout.addWidget(self.pairing)
        layout.addWidget(separator())
        layout.addWidget(label("Settings", "section"))
        layout.addLayout(form)
        layout.addStretch()
        layout.addWidget(self.add_button)
        return panel

    def build_queue(self) -> QWidget:
        self.queue_summary = label("", "muted")
        self.queue_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.table = QueueTable()
        self.table.itemSelectionChanged.connect(self.refresh_queue)
        self.table.cellDoubleClicked.connect(self.open_output)

        self.remove_button = QPushButton("Remove")
        self.remove_button.setProperty("role", "ghost")
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_done_button = QPushButton("Clear finished")
        self.clear_done_button.setProperty("role", "ghost")
        self.clear_done_button.clicked.connect(self.clear_finished)

        top = QHBoxLayout()
        top.addWidget(label("Queue", "section"))
        top.addWidget(self.queue_summary)
        top.addStretch()
        top.addWidget(self.remove_button)
        top.addWidget(self.clear_done_button)

        panel = QFrame()
        panel.setProperty("role", "card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 8)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        return panel

    def build_footer(self) -> QWidget:
        self.status = label("", "muted")
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setFixedWidth(280)
        self.overall_label = label("", "muted")
        self.overall_label.setFixedWidth(36)
        self.overall_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.overall.valueChanged.connect(lambda v: self.overall_label.setText(f"{v}%"))

        footer = QFrame()
        footer.setProperty("role", "footer")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.overall)
        layout.addWidget(self.overall_label)
        return footer

    # --- sources -------------------------------------------------------------

    def pairs(self) -> tuple[list[tuple[Path, Path | None]], str]:
        """Masks and beauties are matched in name order. Returns pairs or an error."""
        masks, beauties = self.mask_field.files, self.beauty_field.files
        if not masks:
            return [], "Add an alpha mask to trace. The beauty render is optional."
        if beauties and len(beauties) != len(masks):
            return (
                [],
                f"{len(beauties)} beauty renders but {len(masks)} masks — the counts must match.",
            )
        return list(zip(masks, beauties or [None] * len(masks))), ""

    def refresh_sources(self) -> None:
        pairs, error = self.pairs()
        self.add_button.setEnabled(bool(pairs))
        self.pairing.setProperty(
            "role", "error" if error and self.mask_field.files else "muted"
        )
        repolish(self.pairing)
        if error:
            self.pairing.setText(error)
        elif len(pairs) == 1:
            target = "the beauty render" if pairs[0][1] else "the mask"
            self.pairing.setText(f"The traced path is saved into {target}.")
        else:
            lines = [f"{b.name if b else '—'}  ←  {m.name}" for m, b in pairs[:4]]
            more = f"<br>… {len(pairs) - 4} more" if len(pairs) > 4 else ""
            self.pairing.setText(
                f"<b>{len(pairs)} jobs</b>, paired by name order:<br>"
                + "<br>".join(lines)
                + more
            )

    def add_dropped(self, path: Path) -> None:
        """Files dropped on the window: names hinting at a mask go to the mask field."""
        if path.is_dir():
            for child in path.iterdir():
                self.add_dropped(child)
        elif is_image(path):
            field = (
                self.mask_field if MASK_WORDS.search(path.stem) else self.beauty_field
            )
            field.files.append(path)

    def browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose output folder", self.output_dir.text()
        )
        if folder:
            self.output_dir.setText(folder)

    def output_for(self, mask: Path, beauty: Path | None) -> Path:
        source = beauty or mask
        folder = (
            Path(self.output_dir.text())
            if self.output_dir.text().strip()
            else source.parent
        )
        output = folder / f"{source.stem}.tif"
        if output.resolve() in {mask.resolve(), beauty and beauty.resolve()}:
            output = folder / f"{source.stem}_path.tif"  # never overwrite an input
        return output

    def add_jobs(self) -> None:
        pairs, _ = self.pairs()
        for mask, beauty in pairs:
            job = Job(
                id=next(self.ids),
                mask=mask,
                beauty=beauty,
                output=self.output_for(mask, beauty),
                alphamax=self.alphamax.value(),
                turdsize=self.turdsize.value(),
                offset=self.offset.value(),
                threshold=self.threshold.value() / 100,
                tolerance=self.tolerance.value(),
                clipping=self.clipping.isChecked(),
                invert=self.invert.isChecked(),
                svg=self.svg.isChecked(),
            )
            self.jobs.append(job)
            self.table.add_job(job)
        self.beauty_field.set_files([])
        self.mask_field.set_files([])
        self.refresh_queue()

    # --- queue ---------------------------------------------------------------

    def job(self, job_id: int) -> Job:
        return next(j for j in self.jobs if j.id == job_id)

    def selected_jobs(self) -> list[Job]:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        ids = {self.table.job_id(row) for row in rows}
        return [j for j in self.jobs if j.id in ids]

    def remove_jobs(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.id in self.run_ids and job.status in (
                Status.PENDING,
                Status.RUNNING,
            ):
                continue  # owned by the running batch
            self.table.removeRow(self.table.row_of(job.id))
            self.jobs.remove(job)
        self.refresh_queue()

    def remove_selected(self) -> None:
        self.remove_jobs(self.selected_jobs())

    def clear_finished(self) -> None:
        self.remove_jobs([j for j in self.jobs if j.status is Status.DONE])

    def open_output(self, row: int, _column: int) -> None:
        job = self.job(self.table.job_id(row))
        folder = (
            job.output.parent
            if job.status is Status.DONE
            else (job.beauty or job.mask).parent
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def refresh_queue(self) -> None:
        running = self.worker is not None
        counts = {s: sum(j.status is s for j in self.jobs) for s in Status}
        runnable = [j for j in self.jobs if j.status is not Status.DONE]

        parts = [f"{len(self.jobs)} job{'s' * (len(self.jobs) != 1)}"]
        parts += [
            f"{counts[s]} {s.value.lower()}"
            for s in (Status.DONE, Status.FAILED)
            if counts[s]
        ]
        self.queue_summary.setText(" · ".join(parts))

        self.run_button.setEnabled(not running and bool(runnable))
        self.run_button.setToolTip("" if runnable else RUN_HINT)
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(not self.cancelling)
        self.remove_button.setEnabled(bool(self.selected_jobs()))
        self.clear_done_button.setEnabled(bool(counts[Status.DONE]))

        batch = [self.job(i) for i in self.run_ids if any(j.id == i for j in self.jobs)]
        if batch:
            done = (
                100 if j.status in (Status.DONE, Status.FAILED) else j.progress
                for j in batch
            )
            self.overall.setValue(sum(done) // len(batch))
        if running:
            finished = sum(
                j.status not in (Status.PENDING, Status.RUNNING) for j in batch
            )
            current = next((j for j in batch if j.status is Status.RUNNING), None)
            name = f" — {(current.beauty or current.mask).name}" if current else ""
            verb = "Cancelling" if self.cancelling else "Processing"
            self.status.setText(
                f"{verb} {min(finished + 1, len(batch))} of {len(batch)}{name}"
            )
        elif not self.jobs:
            self.status.setText(
                "Drop a mask (and optionally its beauty render) to get started."
            )

    # --- batch ---------------------------------------------------------------

    def run_batch(self) -> None:
        jobs = [j for j in self.jobs if j.status is not Status.DONE]
        if not jobs or self.worker:
            return
        for job in jobs:
            job.status, job.progress, job.message = Status.PENDING, 0, ""
            self.table.update_job(job)
        self.run_ids = [j.id for j in jobs]
        self.cancelling = False

        self.worker = BatchWorker(jobs)
        self.worker.job_progress.connect(self.on_progress)
        self.worker.job_finished.connect(self.on_finished)
        self.worker.finished.connect(self.on_batch_finished)
        self.worker.start()
        self.refresh_queue()

    def cancel_batch(self) -> None:
        if self.worker:
            self.cancelling = True
            self.worker.requestInterruption()
            self.refresh_queue()

    def on_progress(self, job_id: int, percent: int, stage: str) -> None:
        job = self.job(job_id)
        job.status, job.progress = Status.RUNNING, percent
        self.table.update_job(job, stage)
        self.refresh_queue()

    def on_finished(self, job_id: int, status: Status, message: str) -> None:
        job = self.job(job_id)
        job.status, job.message = status, message
        if status is not Status.DONE:
            job.progress = 0
        self.table.update_job(job)
        self.refresh_queue()

    def on_batch_finished(self) -> None:
        batch = [j for j in self.jobs if j.id in self.run_ids]
        done = sum(j.status is Status.DONE for j in batch)
        failed = sum(j.status is Status.FAILED for j in batch)
        assert self.worker is not None
        self.worker.deleteLater()
        self.worker = None
        verb = "Cancelled" if self.cancelling else "Finished"
        self.status.setText(
            f"{verb}: {done} of {len(batch)} traced"
            + (f", {failed} failed" if failed else "")
        )
        self.cancelling = False
        self.refresh_queue()

    # --- window --------------------------------------------------------------

    def refresh_theme(self) -> None:
        for job in self.jobs:
            self.table.update_job(job)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.add_dropped(Path(url.toLocalFile()))
        event.acceptProposedAction()
        for field in (self.beauty_field, self.mask_field):
            field.set_files(field.files)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker:
            self.worker.requestInterruption()
            self.worker.wait()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    theme.setup(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
