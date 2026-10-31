"""Genera los sprites de marcador de posición: formas genéricas, no el personaje."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

from kasane_teto.character.states import STATE_LABELS, PetState  # noqa: E402

WIDTH = 240
HEIGHT = 300
OUTPUT = ROOT / "assets" / "character" / "provisional"

STYLE: dict[PetState, tuple[str, float]] = {
    PetState.IDLE: ("#7f8fa6", 1),
    PetState.LISTENING: ("#00a8a8", 3),
    PetState.THINKING: ("#8c7ae6", 2),
    PetState.SPEAKING: ("#44bd32", 5),
    PetState.HAPPY: ("#fbc531", 4),
    PetState.SURPRISED: ("#e1b12c", 4),
    PetState.CONFUSED: ("#718093", 2),
    PetState.ANGRY: ("#e84118", 5),
    PetState.BORED: ("#a4b0be", 1),
}


def draw_frame(state: PetState, frame: int) -> QImage:
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    color = QColor(STYLE[state][0])
    bob = 6 * frame

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(30, 20 + bob, 180, 210 - bob), 70, 70)

    painter.setBrush(QColor("#ffffff"))
    eye_height = 8 if frame == 1 and state is PetState.IDLE else 34
    for x in (80, 136):
        painter.drawEllipse(QRectF(x, 90 + bob + (34 - eye_height) / 2, 24, eye_height))

    painter.setBrush(QColor(0, 0, 0, 170))
    painter.drawRoundedRect(QRectF(10, 244, 220, 44), 14, 14)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI")
    font.setPixelSize(24)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(
        QRectF(10, 244, 220, 44), Qt.AlignmentFlag.AlignCenter, STATE_LABELS[state]
    )
    painter.end()
    return image


def main() -> int:
    app = QGuiApplication(sys.argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = [
        'name = "Provisional"',
        'author = "Proyecto Kasane Teto AI Lite"',
        'license = "Marcador de posición del proyecto; no representa al personaje"',
    ]
    for state, (_, fps) in STYLE.items():
        files = [f"{state.value}_{frame}.png" for frame in range(2)]
        for frame, name in enumerate(files):
            if not draw_frame(state, frame).save(str(OUTPUT / name)):
                raise OSError(f"No se pudo guardar {name}")
        frame_list = ", ".join(f'"{name}"' for name in files)
        manifest += ["", f"[states.{state.value}]", f"frames = [{frame_list}]", f"fps = {fps:g}"]
    (OUTPUT / "manifest.toml").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
