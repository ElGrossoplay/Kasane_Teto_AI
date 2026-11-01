"""Ventana de configuración mínima."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from kasane_teto.core.events import EventBus
from kasane_teto.desktop.hotkey import HOTKEY_LABEL
from kasane_teto.desktop.pet_window import MAX_SCALE, MIN_SCALE, SCALE_STEP


@dataclass(frozen=True)
class VoiceOptions:
    tts_enabled: bool
    models: list[str]
    model: str
    volume: int
    mic_enabled: bool


class SettingsWindow(QDialog):
    def __init__(
        self,
        bus: EventBus,
        always_on_top: bool,
        scale: int,
        packs: list[str],
        current_pack: str,
        data_dir: Path,
        voice: VoiceOptions,
        web_enabled: bool,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Configuración")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._always_on_top = QCheckBox("Mantener la mascota sobre las demás ventanas")
        self._always_on_top.setChecked(always_on_top)
        self._always_on_top.toggled.connect(bus.always_on_top_requested)

        self._scale = QSpinBox()
        self._scale.setRange(MIN_SCALE, MAX_SCALE)
        self._scale.setSingleStep(SCALE_STEP)
        self._scale.setSuffix(" %")
        self._scale.setValue(scale)
        self._scale.valueChanged.connect(bus.scale_requested)

        self._pack = QComboBox()
        self._pack.addItems(packs)
        self._pack.setCurrentText(current_pack)
        self._pack.currentTextChanged.connect(bus.pack_requested)

        self._tts = QCheckBox("Teto habla en voz alta")
        self._tts.setChecked(voice.tts_enabled)
        self._tts.toggled.connect(bus.tts_enabled_requested)

        self._voice = QComboBox()
        self._voice.addItems(voice.models)
        self._voice.setCurrentText(voice.model)
        self._voice.currentTextChanged.connect(bus.voice_model_requested)

        self._volume = QSpinBox()
        self._volume.setRange(0, 100)
        self._volume.setSingleStep(5)
        self._volume.setSuffix(" %")
        self._volume.setValue(voice.volume)
        self._volume.valueChanged.connect(bus.volume_requested)

        self._mic = QCheckBox(f"Activar el micrófono (atajo {HOTKEY_LABEL})")
        self._mic.setChecked(voice.mic_enabled)
        self._mic.toggled.connect(bus.mic_enabled_requested)

        self._web = QCheckBox("Buscar artistas y canciones en Internet (VocaDB)")
        self._web.setToolTip(
            "Solo se envía el nombre por el que preguntas, nunca la conversación."
        )
        self._web.setChecked(web_enabled)
        self._web.toggled.connect(bus.web_enabled_requested)

        data_label = QLabel(str(data_dir))
        data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow(self._always_on_top)
        form.addRow("Tamaño", self._scale)
        form.addRow("Personaje", self._pack)
        form.addRow(self._tts)
        form.addRow("Voz", self._voice)
        form.addRow("Volumen", self._volume)
        form.addRow(self._mic)
        form.addRow(self._web)
        form.addRow("Datos", data_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        bus.always_on_top_changed.connect(self._always_on_top.setChecked)
        bus.scale_changed.connect(self._scale.setValue)
