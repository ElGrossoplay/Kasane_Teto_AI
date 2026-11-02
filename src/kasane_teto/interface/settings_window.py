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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from kasane_teto.core.events import EventBus
from kasane_teto.desktop.hotkey import HOTKEY_LABEL
from kasane_teto.desktop.pet_window import MAX_SCALE, MIN_SCALE, SCALE_STEP
from kasane_teto.interface.apps_window import AppsWindow
from kasane_teto.interface.discord_window import DiscordWindow
from kasane_teto.tools.discord_rpc import DiscordVoice


MIN_COMMENT_MINUTES = 1
MAX_COMMENT_MINUTES = 120


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
        suggest_memories: bool = True,
        save_history: bool = False,
        tools_enabled: bool = False,
        allowed_apps: dict[str, str] | None = None,
        tools_confirm: bool = False,
        comments_enabled: bool = False,
        comments_minutes: int = 10,
        discord: DiscordVoice | None = None,
    ) -> None:
        super().__init__()
        self._discord = discord
        self._bus = bus
        self._allowed_apps = dict(allowed_apps or {})
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

        self._suggest = QCheckBox("Teto pregunta si recordar lo que le cuentas")
        self._suggest.setToolTip("Nunca guarda nada sin que digas que sí.")
        self._suggest.setChecked(suggest_memories)
        self._suggest.toggled.connect(bus.memory_suggestions_requested)

        self._history = QCheckBox("Guardar el historial de conversaciones")
        self._history.setToolTip("Se guarda solo en este equipo y se borra desde Memoria.")
        self._history.setChecked(save_history)
        self._history.toggled.connect(bus.history_enabled_requested)

        self._tools = QCheckBox("Permitir que Teto controle Windows")
        self._tools.setToolTip("Abrir y cerrar programas, carpetas, archivos y webs permitidos.")
        self._tools.setChecked(tools_enabled)
        self._tools.toggled.connect(bus.tools_enabled_requested)
        self._confirm = QCheckBox("Preguntar antes de cada acción")
        self._confirm.setChecked(tools_confirm)
        self._confirm.toggled.connect(bus.tools_confirm_requested)
        self._apps_button = QPushButton("Aplicaciones permitidas…")
        self._apps_button.clicked.connect(self._open_apps)
        bus.allowed_apps_requested.connect(self._remember_apps)

        self._comments = QCheckBox("Teto comenta por su cuenta")
        self._comments.setToolTip("Mira el título de la ventana activa. Nunca captura la pantalla.")
        self._comments.setChecked(comments_enabled)
        self._comments.toggled.connect(bus.comments_enabled_requested)
        self._comment_minutes = QSpinBox()
        self._comment_minutes.setRange(MIN_COMMENT_MINUTES, MAX_COMMENT_MINUTES)
        self._comment_minutes.setSuffix(" min")
        self._comment_minutes.setValue(comments_minutes)
        self._comment_minutes.valueChanged.connect(bus.comments_minutes_requested)

        self._discord_button = QPushButton("Discord y contactos…")
        self._discord_button.setEnabled(discord is not None)
        self._discord_button.clicked.connect(self._open_discord)

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
        form.addRow(self._suggest)
        form.addRow(self._history)
        form.addRow(self._tools)
        form.addRow(self._confirm)
        form.addRow(self._apps_button)
        form.addRow(self._comments)
        form.addRow("Tiempo sin hablar", self._comment_minutes)
        form.addRow(self._discord_button)
        form.addRow("Datos", data_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Cerrar")
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        bus.always_on_top_changed.connect(self._always_on_top.setChecked)
        bus.scale_changed.connect(self._scale.setValue)

    def _remember_apps(self, apps: dict[str, str]) -> None:
        self._allowed_apps = dict(apps)

    def _open_apps(self) -> None:
        AppsWindow(self._bus, self._allowed_apps, self).exec()

    def _open_discord(self) -> None:
        if self._discord is not None:
            DiscordWindow(self._discord, self).exec()
