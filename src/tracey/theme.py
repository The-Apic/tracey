"""Colors, fonts and the stylesheet. Follows the system light / dark setting."""

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

RESOURCES = Path(__file__).parent / "resources"

DARK = {
    "window": "#0e1015",
    "surface": "#161920",
    "raised": "#1d2129",
    "hover": "#252a34",
    "border": "#262b35",
    "border-strong": "#353b47",
    "text": "#e7e9ee",
    "muted": "#8b93a3",
    "faint": "#5d6473",
    "accent": "#6366f1",
    "accent-hover": "#787bf6",
    "accent-soft": "rgba(99, 102, 241, 0.16)",
    "on-accent": "#ffffff",
    "success": "#34c38f",
    "danger": "#f0616d",
    "danger-soft": "rgba(240, 97, 109, 0.14)",
    "track": "rgba(255, 255, 255, 0.07)",
    "selection": "rgba(99, 102, 241, 0.22)",
    "row-alt": "rgba(255, 255, 255, 0.018)",
}

LIGHT = {
    "window": "#f4f5f8",
    "surface": "#ffffff",
    "raised": "#f6f7f9",
    "hover": "#eceef2",
    "border": "#e3e6ec",
    "border-strong": "#cfd4dc",
    "text": "#171a21",
    "muted": "#646c7b",
    "faint": "#9aa1ad",
    "accent": "#5145e5",
    "accent-hover": "#4338ca",
    "accent-soft": "rgba(81, 69, 229, 0.10)",
    "on-accent": "#ffffff",
    "success": "#1f9d6b",
    "danger": "#d93f4c",
    "danger-soft": "rgba(217, 63, 76, 0.10)",
    "track": "rgba(15, 23, 42, 0.07)",
    "selection": "rgba(81, 69, 229, 0.12)",
    "row-alt": "rgba(15, 23, 42, 0.022)",
}

FONTS = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "SF Pro Text",
    "Inter",
    "Helvetica Neue",
    "Arial",
]

tokens = DARK


def is_dark(app: QApplication) -> bool:
    return app.styleHints().colorScheme() != Qt.ColorScheme.Light


def color(name: str) -> QColor:
    return QColor(tokens[name])


def icon() -> QIcon:
    if sys.platform == "win32":
        return QIcon(str(RESOURCES / "tracey.ico"))
    if sys.platform == "darwin":
        return QIcon(str(RESOURCES / "tracey.icns"))
    return QIcon(str(RESOURCES / "icon.png"))


def logo(size: int, ratio: float = 1) -> QPixmap:
    """In-app logo. Unlike the icon files' small sizes, it keeps the anchors."""
    pixels = round(size * ratio)
    pixmap = QPixmap(str(RESOURCES / "logo.png")).scaled(
        pixels,
        pixels,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def set_app_id() -> None:
    """Let Windows show our icon in the taskbar instead of python.exe's."""
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("theapic.tracey")


def palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: "window",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "surface",
        QPalette.ColorRole.AlternateBase: "raised",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "raised",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.PlaceholderText: "faint",
        QPalette.ColorRole.ToolTipBase: "raised",
        QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.HighlightedText: "on-accent",
        QPalette.ColorRole.Link: "accent",
        QPalette.ColorRole.Mid: "border",
    }
    for role, name in roles.items():
        p.setColor(role, color(name))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, color("faint"))
    return p


STYLE = """
* { outline: none; }
QMainWindow, QWidget#root { background: @window; }
QToolTip { background: @raised; color: @text; border: 1px solid @border-strong; border-radius: 6px; padding: 5px 8px; }

/* text */
QLabel { color: @text; }
QLabel[role="apptitle"] { font-size: 15px; font-weight: 600; }
QLabel[role="section"] { font-size: 13px; font-weight: 600; }
QLabel[role="fieldtitle"] { font-weight: 600; }
QLabel[role="muted"] { color: @muted; }
QLabel[role="error"] { color: @danger; }
QLabel[role="required"], QLabel[role="optional"] { border-radius: 9px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
QLabel[role="required"] { background: @accent-soft; color: @accent; }
QLabel[role="optional"] { background: @track; color: @muted; }
QLabel[role="thumbnail"] { background: @raised; border: 1px solid @border; border-radius: 8px; font-size: 22px; color: @faint; }

/* layout chrome */
QFrame[role="topbar"] { background: @surface; border-bottom: 1px solid @border; }
QFrame[role="footer"] { background: @surface; border-top: 1px solid @border; }
QFrame[role="card"] { background: @surface; border: 1px solid @border; border-radius: 12px; }
QFrame[role="separator"] { background: @border; border: none; }
QSplitter::handle { background: transparent; }

QFrame[role="dropfield"] { background: @raised; border: 1px dashed @border-strong; border-radius: 10px; }
QFrame[role="dropfield"]:hover { border-color: @faint; }
QFrame[role="dropfield"][hover="true"] { background: @accent-soft; border: 1px solid @accent; }

/* buttons */
QPushButton { background: @raised; color: @text; border: 1px solid @border-strong; border-radius: 7px; padding: 6px 14px; font-weight: 500; }
QPushButton:hover { background: @hover; }
QPushButton:pressed { background: @border; }
QPushButton:disabled { color: @faint; border-color: @border; background: transparent; }
QPushButton[role="accent"] { background: @accent; color: @on-accent; border: 1px solid @accent; font-weight: 600; padding: 7px 18px; }
QPushButton[role="accent"]:hover { background: @accent-hover; border-color: @accent-hover; }
QPushButton[role="accent"]:disabled { background: @accent-soft; border-color: transparent; color: @faint; }
QPushButton[role="ghost"] { background: transparent; border-color: transparent; color: @muted; padding: 4px 10px; }
QPushButton[role="ghost"]:hover { background: @hover; color: @text; }
QPushButton[role="ghost"]:disabled { color: @faint; }
QPushButton[role="danger"] { color: @danger; }
QPushButton[role="square"] { padding: 6px 0; }
QPushButton[role="danger"]:hover { background: @danger-soft; border-color: @danger; }

/* inputs */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background: @raised; color: @text; border: 1px solid @border-strong; border-radius: 7px;
    padding: 5px 8px; selection-background-color: @accent; selection-color: @on-accent;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: @faint; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: @accent; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; width: 20px; border: none; background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 7px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 7px; }
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: @hover; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@res/chevron-up.svg); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@res/chevron-down.svg); width: 10px; height: 10px; }

QCheckBox { color: @text; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid @border-strong; background: @raised; }
QCheckBox::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: url(@res/check.svg); }

/* queue */
QTableWidget {
    background: transparent; border: none; color: @text;
    alternate-background-color: @row-alt; selection-background-color: @selection; selection-color: @text;
}
QTableWidget::item { padding: 0 10px; border-bottom: 1px solid @border; }
QTableWidget::item:selected { background: @selection; }
QHeaderView { background: transparent; }
QHeaderView::section {
    background: transparent; color: @muted; border: none; border-bottom: 1px solid @border;
    padding: 8px 10px; font-size: 12px; font-weight: 600; text-align: left;
}
QTableCornerButton::section { background: transparent; border: none; }

QProgressBar { background: @track; border: none; border-radius: 3px; max-height: 6px; color: transparent; }
QProgressBar::chunk { background: @accent; border-radius: 3px; }
QProgressBar[status="done"]::chunk { background: @success; }
QFrame[role="footer"] QProgressBar { max-height: 8px; border-radius: 4px; }
QFrame[role="footer"] QProgressBar::chunk { border-radius: 4px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: @border-strong; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: @faint; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; height: 0; width: 0; }
"""


def stylesheet() -> str:
    css = STYLE.replace("@res", RESOURCES.as_posix())
    # longest names first, so @border-strong is not eaten by @border
    for name in sorted(tokens, key=len, reverse=True):
        css = css.replace(f"@{name}", tokens[name])
    return css


def apply(app: QApplication) -> None:
    global tokens
    tokens = DARK if is_dark(app) else LIGHT
    app.setPalette(palette())
    app.setStyleSheet(stylesheet())


def setup(app: QApplication) -> None:
    set_app_id()
    app.setStyle("Fusion")
    app.setWindowIcon(icon())
    font = QFont()
    font.setFamilies(FONTS)
    font.setPixelSize(13)
    app.setFont(font)
    apply(app)
    app.styleHints().colorSchemeChanged.connect(lambda _: apply(app))
