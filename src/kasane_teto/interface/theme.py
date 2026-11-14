"""Aspecto común de todas las ventanas: paleta clara u oscura con el rojo de Teto.

Se usa el estilo Fusion de Qt con una paleta y una hoja de estilos corta; no carga imágenes ni
fuentes, así que no añade memoria apreciable.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("auto", "oscuro", "claro")


@dataclass(frozen=True)
class Colors:
    window: str
    base: str
    raised: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    user_bubble: str
    teto_bubble: str


DARK = Colors(
    window="#201d22",
    base="#17151a",
    raised="#2d2930",
    border="#3d3842",
    text="#eee9ef",
    muted="#a49ba8",
    accent="#d8344f",
    accent_hover="#e9506a",
    accent_text="#ffffff",
    user_bubble="#4a2029",
    teto_bubble="#2a262d",
)
LIGHT = Colors(
    window="#f6f2f4",
    base="#ffffff",
    raised="#ffffff",
    border="#d9d0d5",
    text="#221d23",
    muted="#75697a",
    accent="#c92643",
    accent_hover="#de3f5b",
    accent_text="#ffffff",
    user_bubble="#fbdde3",
    teto_bubble="#eee8eb",
)

_current = DARK


def colors() -> Colors:
    """Colores del tema aplicado, para lo que se pinta a mano (chat y bocadillo)."""
    return _current


def is_dark(mode: str) -> bool:
    if mode == "claro":
        return False
    if mode == "oscuro":
        return True
    return QGuiApplication.styleHints().colorScheme() is not Qt.ColorScheme.Light


def stylesheet(c: Colors) -> str:
    return f"""
QWidget {{ font-size: 10pt; }}
QToolTip {{ color: {c.text}; background: {c.raised}; border: 1px solid {c.border}; padding: 4px; }}
QPushButton {{
    background: {c.raised}; color: {c.text}; border: 1px solid {c.border};
    border-radius: 6px; padding: 5px 12px;
}}
QPushButton:hover {{ border-color: {c.accent}; }}
QPushButton:pressed {{ background: {c.border}; }}
QPushButton:disabled {{ color: {c.muted}; border-color: {c.border}; background: {c.window}; }}
QPushButton[primary="true"] {{ background: {c.accent}; color: {c.accent_text}; border-color: {c.accent}; }}
QPushButton[primary="true"]:hover {{ background: {c.accent_hover}; }}
QPushButton[primary="true"]:disabled {{ background: {c.border}; color: {c.muted}; border-color: {c.border}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {c.base}; color: {c.text}; border: 1px solid {c.border};
    border-radius: 6px; padding: 4px 6px; selection-background-color: {c.accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {c.accent};
}}
QTabWidget::pane {{ border: 1px solid {c.border}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {c.muted}; padding: 6px 14px;
    border: none; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {c.text}; border-bottom-color: {c.accent}; }}
QTabBar::tab:hover {{ color: {c.text}; }}
QMenu {{ background: {c.raised}; color: {c.text}; border: 1px solid {c.border}; padding: 4px; }}
QMenu::item {{ padding: 5px 24px 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c.accent}; color: {c.accent_text}; }}
QMenu::item:disabled {{ color: {c.muted}; }}
QMenu::separator {{ height: 1px; background: {c.border}; margin: 4px 8px; }}
QLabel[role="muted"] {{ color: {c.muted}; }}
QLabel[role="title"] {{ font-size: 12pt; font-weight: 600; }}
"""


def apply_theme(app: QApplication, mode: str = "auto") -> Colors:
    """Aplica el tema a toda la app y devuelve sus colores."""
    global _current
    _current = DARK if is_dark(mode) else LIGHT
    c = _current
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.window,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.base,
        QPalette.ColorRole.AlternateBase: c.raised,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.Button: c.raised,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.ToolTipBase: c.raised,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.accent_text,
        QPalette.ColorRole.Link: c.accent_hover,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.muted))
    app.setStyle("Fusion")
    app.setPalette(palette)
    app.setStyleSheet(stylesheet(c))
    return c
