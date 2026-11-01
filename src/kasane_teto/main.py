"""Punto de entrada: crea los componentes y los conecta por el EventBus."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from kasane_teto.character.pack import CharacterPack, PackError, list_packs, load_pack
from kasane_teto.character.states import PetState
from kasane_teto.core.conversation import ConversationService
from kasane_teto.core.events import EventBus
from kasane_teto.core.logging_setup import setup_logging
from kasane_teto.core.paths import (
    character_root,
    data_dir,
    default_config_path,
    knowledge_root,
    models_dir,
    workers_dir,
)
from kasane_teto.core.resource_manager import ResourceManager
from kasane_teto.core.settings import Settings
from kasane_teto.core.single_instance import SingleInstance
from kasane_teto.desktop.animator import SpriteAnimator
from kasane_teto.desktop.hotkey import HOTKEY_LABEL, GlobalHotkey
from kasane_teto.desktop.pet_window import PetWindow
from kasane_teto.desktop.tray import TrayIcon
from kasane_teto.interface.chat_window import ChatWindow
from kasane_teto.interface.settings_window import SettingsWindow, VoiceOptions
from kasane_teto.memory.knowledge import KnowledgeBase, KnowledgeError
from kasane_teto.voice.audio import AudioPlayer, AudioRecorder
from kasane_teto.voice.engines import STTEngine, TTSEngine
from kasane_teto.voice.listening import ListenService
from kasane_teto.voice.speech import SpeechService

FALLBACK_PACK = "provisional"

log = logging.getLogger(__name__)


class TetoApp(QObject):
    def __init__(self, app: QApplication, settings: Settings, user_dir: Path) -> None:
        super().__init__()
        self._app = app
        self._settings = settings
        self._user_dir = user_dir
        self._bus = EventBus(self)
        self._settings_window: SettingsWindow | None = None

        pack = self._load_configured_pack()
        self._pack_id = pack.id
        self._animator = SpriteAnimator(pack, self)
        self._pet = PetWindow(self._animator, settings, self._bus)
        self._tray = TrayIcon(
            QIcon(self._animator.current_pixmap()), self._pet.always_on_top, self._bus, self
        )
        self._resources = ResourceManager(
            settings, models_dir(), user_dir / "logs" / "llama-server.log", self
        )
        knowledge = self._load_knowledge()
        self._conversation = ConversationService(
            self._bus, self._resources, settings, knowledge, self
        )
        self._chat_window = ChatWindow(self._bus)
        self._speech = SpeechService(
            self._bus, settings, self._new_tts(), AudioPlayer(), self
        )
        stt = STTEngine(
            models_dir(),
            workers_dir(),
            int(settings.get("voice.stt_threads", 4)),
            f"Conversación con Teto. {knowledge.vocabulary()}.",
        )
        self._listen = ListenService(self._bus, settings, stt, AudioRecorder(), self)
        self._hotkey = GlobalHotkey(lambda: self._bus.listen_toggled.emit())
        if self._listen.enabled:
            self._hotkey.register()
        self._bus.mic_enabled_requested.connect(self._on_mic_enabled)
        self._bus.volume_requested.connect(lambda v: settings.set("voice.volume", v))
        self._bus.voice_model_requested.connect(self._change_voice)

        self._bus.pet_state_requested.connect(self._animator.set_state)
        self._bus.pet_visibility_toggled.connect(self._pet.toggle_visibility)
        self._bus.always_on_top_requested.connect(self._pet.set_always_on_top)
        self._bus.scale_requested.connect(self._pet.set_scale)
        self._bus.pack_requested.connect(self._change_pack)
        self._bus.settings_requested.connect(self._open_settings)
        self._bus.chat_requested.connect(self._chat_window.open)
        self._bus.ai_unload_requested.connect(self._resources.request_unload)
        self._bus.quit_requested.connect(app.quit)
        app.aboutToQuit.connect(self._shutdown)

    def start(self) -> None:
        self._tray.show()
        self._pet.show()

    def show_pet(self) -> None:
        self._pet.show()
        self._pet.raise_()

    def _new_tts(self) -> TTSEngine:
        voice = str(self._settings.get("voice.model", "es_MX-claude-high"))
        return TTSEngine(models_dir(), workers_dir(), voice)

    def _change_voice(self, voice: str) -> None:
        self._settings.set("voice.model", voice)
        self._speech.set_engine(self._new_tts())

    def _on_mic_enabled(self, enabled: bool) -> None:
        if not enabled:
            self._hotkey.unregister()
        elif not self._hotkey.register():
            self._bus.voice_status.emit(f"El atajo {HOTKEY_LABEL} no está disponible.")

    @staticmethod
    def _load_knowledge() -> KnowledgeBase:
        try:
            return KnowledgeBase.load(knowledge_root())
        except KnowledgeError:
            log.exception("Conocimiento no válido; Teto sigue sin fichas")
            return KnowledgeBase([])

    def _load_configured_pack(self) -> CharacterPack:
        pack_id = str(self._settings.get("pet.pack", FALLBACK_PACK))
        try:
            return load_pack(character_root() / pack_id)
        except PackError:
            log.exception("Paquete '%s' no válido; se usa el provisional", pack_id)
            return load_pack(character_root() / FALLBACK_PACK)

    def _change_pack(self, pack_id: str) -> None:
        try:
            pack = load_pack(character_root() / pack_id)
            self._animator.set_pack(pack)
        except PackError as exc:
            log.exception("No se pudo cargar el paquete '%s'", pack_id)
            QMessageBox.warning(None, "Personaje", f"No se pudo cargar el personaje.\n{exc}")
            return
        self._pack_id = pack.id
        self._settings.set("pet.pack", pack.id)
        self._pet.refresh_size()

    def _open_settings(self) -> None:
        if self._settings_window is not None:
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        window = SettingsWindow(
            self._bus,
            self._pet.always_on_top,
            self._pet.scale_percent,
            list_packs(character_root()),
            self._pack_id,
            self._user_dir,
            VoiceOptions(
                tts_enabled=self._speech.enabled,
                models=sorted(p.stem for p in (models_dir() / "piper" / "voices").glob("*.onnx")),
                model=str(self._settings.get("voice.model", "")),
                volume=int(self._settings.get("voice.volume", 80)),
                mic_enabled=self._listen.enabled,
            ),
        )
        window.destroyed.connect(self._on_settings_closed)
        self._settings_window = window
        window.show()

    def _on_settings_closed(self) -> None:
        self._settings_window = None

    def _shutdown(self) -> None:
        self._bus.generation_stop_requested.emit()
        self._pet.save_position()
        self._tray.hide()
        self._hotkey.unregister()
        self._listen.shutdown()
        self._speech.shutdown()
        self._resources.shutdown()


def main() -> int:
    user_dir = data_dir()
    setup_logging(user_dir)
    app = QApplication(sys.argv)
    app.setApplicationName("Kasane Teto AI")
    app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance(user_dir)
    if not instance.acquire():
        log.info("Ya hay una instancia en ejecución")
        return 0

    try:
        settings = Settings(default_config_path(), user_dir / "settings.json")
        teto = TetoApp(app, settings, user_dir)
    except (OSError, ValueError, PackError) as exc:
        log.exception("No se pudo iniciar la app")
        QMessageBox.critical(None, "Kasane Teto AI", f"No se pudo iniciar la app.\n{exc}")
        return 1

    instance.activated.connect(teto.show_pet)
    teto.start()
    log.info("App iniciada; estado inicial %s", PetState.IDLE.value)
    code = app.exec()
    instance.release()
    return code


if __name__ == "__main__":
    sys.exit(main())
