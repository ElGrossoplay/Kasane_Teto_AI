"""Punto de entrada: crea los componentes y los conecta por el EventBus."""

from __future__ import annotations

import logging
import sys
import time
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from kasane_teto.character.pack import CharacterPack, PackError, list_packs, load_pack
from kasane_teto.character.states import PetState
from kasane_teto.core.activity import Activity, ActivityService
from kasane_teto.core.comments import CommentService
from kasane_teto.core.conversation import ConversationService
from kasane_teto.core.events import EventBus
from kasane_teto.core.logging_setup import setup_logging
from kasane_teto.core.paths import (
    character_root,
    data_dir,
    default_config_path,
    is_frozen,
    knowledge_root,
    models_dir,
    project_root,
    workers_dir,
)
from kasane_teto.core.resource_manager import ResourceManager
from kasane_teto.core.settings import Settings
from kasane_teto.core.single_instance import SingleInstance
from kasane_teto.core.updates import code_changed_since, relaunch
from kasane_teto.desktop.animator import SpriteAnimator
from kasane_teto.desktop.bubble import SpeechBubble
from kasane_teto.desktop.hotkey import CHAT, HOTKEY_LABEL, SHOW, GlobalHotkey
from kasane_teto.desktop.live2d_animator import Live2DAnimator, available_looks
from kasane_teto.desktop.pet_window import PetWindow
from kasane_teto.desktop.tray import TrayIcon
from kasane_teto.interface.chat_window import ChatWindow
from kasane_teto.interface.memory_window import MemoryWindow
from kasane_teto.interface.settings_window import SettingsWindow, VoiceOptions
from kasane_teto.interface.theme import apply_theme
from kasane_teto.memory.knowledge import KnowledgeBase, KnowledgeError
from kasane_teto.memory.store import MemoryStore, MemoryStoreError
from kasane_teto.tools.discord_rpc import DiscordVoice
from kasane_teto.tools.info_sources import InfoClient, InfoLookup
from kasane_teto.tools.registry import ToolRegistry
from kasane_teto.tools.secure_store import SecureStore
from kasane_teto.tools.vocadb import VocaDBClient
from kasane_teto.tools.web_lookup import MusicLookup
from kasane_teto.voice.audio import AudioPlayer, AudioRecorder
from kasane_teto.voice.engines import STTEngine, TTSEngine
from kasane_teto.voice.listening import ListenService
from kasane_teto.voice.speech import SpeechService
from kasane_teto.voice.transcript import fix_transcript

FALLBACK_PACK = "provisional"
LIVE2D_PACK = "live2d"
DIAGNOSTICS_FLAG = "--diagnostico"
IDLE_MAX_FPS = 2
GAME_LISTEN_REASON = "En modo juego no te escucho, para no quitarle CPU al juego."

log = logging.getLogger(__name__)


class TetoApp(QObject):
    def __init__(self, app: QApplication, settings: Settings, user_dir: Path) -> None:
        super().__init__()
        self._app = app
        self._settings = settings
        self._user_dir = user_dir
        self._bus = EventBus(self)
        self._settings_window: SettingsWindow | None = None
        apply_theme(app, str(settings.get("interface.theme", "auto")))

        pack = self._load_configured_pack()
        self._pack_id = pack.id
        self._animator = SpriteAnimator(pack, self)
        self._pet = PetWindow(self._animator, settings, self._bus)
        self._tray = TrayIcon(
            QIcon(self._animator.current_pixmap()), self._pet.always_on_top, self._bus, self
        )
        if settings.get("pet.pack") == LIVE2D_PACK:
            self._use_live2d()
        self._resources = ResourceManager(
            settings, models_dir(), user_dir / "logs" / "llama-server.log", self
        )
        knowledge = self._load_knowledge()
        self._memory = self._open_memory_store(user_dir)
        self._memory_window: MemoryWindow | None = None
        self._discord = DiscordVoice(SecureStore(user_dir / "discord.bin"))
        tools = ToolRegistry(
            settings, user_dir / "logs" / "actions.log", discord=self._discord
        )
        self._conversation = ConversationService(
            self._bus,
            self._resources,
            settings,
            knowledge,
            MusicLookup(VocaDBClient(user_dir / "vocadb_cache.sqlite3")),
            self,
            memory=self._memory,
            tools=tools,
            info=InfoLookup(InfoClient(user_dir / "info_cache.sqlite3")),
        )
        self._comments = CommentService(
            self._bus, settings, tools, self._conversation.comment, self
        )
        self._chat_window = ChatWindow(self._bus, settings)
        self._bubble = SpeechBubble()
        self._bubble.set_enabled(bool(settings.get("pet.bubble", True)))
        self._speech = SpeechService(
            self._bus, settings, self._new_tts(), AudioPlayer(), self
        )
        stt = STTEngine(
            models_dir(),
            workers_dir(),
            int(settings.get("voice.stt_threads", 4)),
            knowledge.vocabulary(),
            str(settings.get("voice.stt_model", "large-v3-turbo")),
        )
        self._listen = ListenService(
            self._bus,
            settings,
            stt,
            AudioRecorder(),
            self,
            partial(fix_transcript, correct_names=knowledge.correct_names),
        )
        self._hotkey = GlobalHotkey(lambda: self._bus.listen_toggled.emit())
        if self._listen.enabled:
            self._hotkey.register()
        # Atajos de manejo: como el de hablar, con RegisterHotKey y sin ganchos de teclado.
        self._shortcuts = [
            GlobalHotkey(lambda: self._bus.chat_requested.emit(), CHAT),
            GlobalHotkey(lambda: self._bus.pet_visibility_toggled.emit(), SHOW),
        ]
        self._set_shortcuts(True)
        self._activity = ActivityService(self._bus, settings, self)
        self._activity.changed.connect(self._apply_activity)
        self._connect_bubble()
        self._bus.mic_enabled_requested.connect(self._on_mic_enabled)
        self._bus.volume_requested.connect(lambda v: settings.set("voice.volume", v))
        self._bus.voice_model_requested.connect(self._change_voice)

        self._bus.pet_state_requested.connect(lambda state: self._pet.animator.set_state(state))
        self._bus.speech_active.connect(lambda active: self._pet.animator.set_talking(active))
        self._bus.gesture_requested.connect(lambda name: self._pet.animator.play_gesture(name))
        self._bus.look_toggled.connect(self._toggle_look)
        self._bus.low_performance_requested.connect(self._set_low_performance)
        self._tray.set_low_performance(bool(settings.get("pet.low_performance", False)))
        self._bus.theme_requested.connect(self._change_theme)
        self._bus.live2d_model_requested.connect(self._change_live2d_model)
        self._bus.pet_visibility_toggled.connect(self._pet.toggle_visibility)
        self._bus.always_on_top_requested.connect(self._pet.set_always_on_top)
        self._bus.scale_requested.connect(self._pet.set_scale)
        self._bus.pack_requested.connect(self._change_pack)
        self._bus.settings_requested.connect(self._open_settings)
        self._bus.memory_panel_requested.connect(self._open_memory_window)
        self._bus.chat_requested.connect(self._chat_window.open)
        self._bus.ai_unload_requested.connect(self._resources.request_unload)
        self._bus.quit_requested.connect(app.quit)
        app.aboutToQuit.connect(self._shutdown)

    def start(self) -> None:
        self._tray.show()
        self._pet.show()
        self._pet.animator.play_gesture("wave")

    def _connect_bubble(self) -> None:
        """El bocadillo repite lo que va al chat; con el chat abierto sobra."""
        bus, bubble = self._bus, self._bubble
        bus.user_message.connect(lambda _text: bubble.begin())
        bus.assistant_token.connect(bubble.append)
        bus.assistant_done.connect(bubble.finish)
        bus.assistant_error.connect(bubble.say)
        bus.assistant_status.connect(bubble.set_status)
        bus.voice_status.connect(bubble.set_status)
        bus.bubble_enabled_requested.connect(self._set_bubble_enabled)
        bus.always_on_top_changed.connect(lambda _on: self._place_bubble())
        self._pet.geometry_changed.connect(self._place_bubble)
        self._chat_window.visibility_changed.connect(self._place_bubble)
        self._place_bubble()

    def _place_bubble(self) -> None:
        self._bubble.set_anchor(self._pet.geometry())
        self._bubble.set_on_top(self._pet.is_on_top)
        self._bubble.set_blocked(
            not self._pet.isVisible()
            or self._chat_window.isVisible()
            or self._activity.state is Activity.GAME
        )

    def _set_bubble_enabled(self, enabled: bool) -> None:
        self._settings.set("pet.bubble", enabled)
        self._bubble.set_enabled(enabled)

    def _change_theme(self, theme: str) -> None:
        self._settings.set("interface.theme", theme)
        apply_theme(self._app, theme)

    def _set_shortcuts(self, enabled: bool) -> None:
        """En modo juego se sueltan: el juego recibe todas sus teclas."""
        for shortcut in self._shortcuts:
            if enabled and self._settings.get("interface.shortcuts", True):
                shortcut.register()
            else:
                shortcut.unregister()

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
        if not enabled or self._activity.state is Activity.GAME:
            self._hotkey.unregister()
        elif not self._hotkey.register():
            self._bus.voice_status.emit(f"El atajo {HOTKEY_LABEL} no está disponible.")

    def _apply_activity(self, state: Activity) -> None:
        """Modo juego: GPU libre, sin oído ni atajo, quieta y nunca encima del juego."""
        game = state is Activity.GAME
        suspended = state is Activity.SUSPENDED
        self._resources.set_game_mode(game)
        self._pet.set_game_mode(game)
        self._pet.animator.set_pace(
            still=game or suspended, max_fps=IDLE_MAX_FPS if state is Activity.IDLE else None
        )
        self._listen.set_blocked(GAME_LISTEN_REASON if game else "")
        if game:
            self._hotkey.unregister()
        elif self._listen.enabled:
            self._hotkey.register()
        self._set_shortcuts(not game)
        self._place_bubble()
        if suspended:
            self._resources.request_unload()
            self._listen.release()
            self._speech.release()
        self._comments.set_paused(suspended)
        self._tray.set_activity(state.value, game, suspended)

    @staticmethod
    def _open_memory_store(user_dir: Path) -> MemoryStore | None:
        try:
            return MemoryStore(user_dir / "memory.sqlite3")
        except MemoryStoreError:
            log.exception("Memoria no disponible; Teto sigue sin recuerdos")
            return None

    def _open_memory_window(self) -> None:
        if self._memory_window is not None:
            self._memory_window.raise_()
            self._memory_window.activateWindow()
            return
        if self._memory is None:
            QMessageBox.warning(None, "Memoria", "La memoria no está disponible.")
            return
        window = MemoryWindow(self._memory)
        window.destroyed.connect(self._on_memory_window_closed)
        self._memory_window = window
        window.show()

    def _on_memory_window_closed(self) -> None:
        self._memory_window = None

    @staticmethod
    def _load_knowledge() -> KnowledgeBase:
        try:
            return KnowledgeBase.load(knowledge_root())
        except KnowledgeError:
            log.exception("Conocimiento no válido; Teto sigue sin fichas")
            return KnowledgeBase([])

    def _live2d_model(self) -> Path | None:
        path = Path(str(self._settings.get("pet.live2d_model", "") or ""))
        return path if path.name.endswith(".model3.json") and path.is_file() else None

    def _use_live2d(self) -> bool:
        """Los sprites quedan de respaldo: si el modelo falla, la mascota no desaparece."""
        model = self._live2d_model()
        if model is None:
            log.warning("No hay modelo Live2D configurado: se usan los sprites")
            return False
        animator = Live2DAnimator(
            model, self._user_dir / "live2d_cache", self, cursor=self._pet.cursor_in_pixels
        )
        animator.failed.connect(self._on_live2d_failed)
        looks = available_looks(model)
        active = [n for n in self._settings.get("pet.live2d_looks", []) or [] if n in looks]
        animator.set_looks(active)
        animator.set_low_performance(bool(self._settings.get("pet.low_performance", False)))
        self._tray.set_looks(looks, active)
        self._pet.set_animator(animator)
        self._pack_id = LIVE2D_PACK
        return True

    def _toggle_look(self, name: str, enabled: bool) -> None:
        """Cambia el aspecto (chibi, con micrófono…) y lo recuerda."""
        active = [n for n in self._settings.get("pet.live2d_looks", []) or [] if n != name]
        if enabled:
            active.append(name)
        self._settings.set("pet.live2d_looks", active)
        self._pet.animator.set_looks(active)

    def _set_low_performance(self, low: bool) -> None:
        self._settings.set("pet.low_performance", low)
        self._pet.animator.set_low_performance(low)
        self._tray.set_low_performance(low)

    def _on_live2d_failed(self, reason: str) -> None:
        log.error("Live2D desactivado en esta sesión: %s", reason)
        failed = self._pet.animator
        if failed is self._animator:
            return
        self._pet.set_animator(self._animator)
        self._tray.set_looks([], [])
        failed.shutdown()
        failed.deleteLater()
        self._tray.notify("No pude mostrar el modelo Live2D: uso los sprites. Mira el registro.")

    def _change_live2d_model(self, path: str) -> None:
        self._settings.set("pet.live2d_model", path)
        if self._pack_id == LIVE2D_PACK:
            self._change_pack(LIVE2D_PACK)

    def _load_configured_pack(self) -> CharacterPack:
        pack_id = str(self._settings.get("pet.pack", FALLBACK_PACK))
        if pack_id == LIVE2D_PACK:
            pack_id = FALLBACK_PACK
        try:
            return load_pack(character_root() / pack_id)
        except PackError:
            log.exception("Paquete '%s' no válido; se usa el provisional", pack_id)
            return load_pack(character_root() / FALLBACK_PACK)

    def _change_pack(self, pack_id: str) -> None:
        current = self._pet.animator
        if pack_id == LIVE2D_PACK:
            if not self._use_live2d():
                QMessageBox.warning(
                    None, "Personaje", "Elige primero el archivo .model3.json del modelo Live2D."
                )
                return
            self._settings.set("pet.pack", LIVE2D_PACK)
        else:
            try:
                pack = load_pack(character_root() / pack_id)
                self._animator.set_pack(pack)
            except PackError as exc:
                log.exception("No se pudo cargar el paquete '%s'", pack_id)
                QMessageBox.warning(None, "Personaje", f"No se pudo cargar el personaje.\n{exc}")
                return
            self._pack_id = pack.id
            self._settings.set("pet.pack", pack.id)
            if current is not self._animator:
                self._pet.set_animator(self._animator)
                self._tray.set_looks([], [])
            self._pet.refresh_size()
        if current is not self._animator and current is not self._pet.animator:
            current.shutdown()
            current.deleteLater()
        self._apply_activity(self._activity.state)

    def _open_settings(self) -> None:
        if self._settings_window is not None:
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        packs = list_packs(character_root())
        if self._live2d_model() is not None:
            packs.append(LIVE2D_PACK)
        window = SettingsWindow(
            self._bus,
            self._pet.always_on_top,
            self._pet.scale_percent,
            packs,
            self._pack_id,
            self._user_dir,
            VoiceOptions(
                tts_enabled=self._speech.enabled,
                models=sorted(p.stem for p in (models_dir() / "piper" / "voices").glob("*.onnx")),
                model=str(self._settings.get("voice.model", "")),
                volume=int(self._settings.get("voice.volume", 80)),
                mic_enabled=self._listen.enabled,
            ),
            self._conversation.web_enabled,
            self._conversation.suggestions_enabled,
            self._conversation.history_enabled,
            self._conversation.tools_enabled,
            dict(self._settings.get("tools.apps", {})),
            bool(self._settings.get("tools.confirm", False)),
            self._comments.enabled,
            int(self._settings.get("comments.minutes", 10)),
            self._discord,
            self._activity.auto_enabled,
            self._conversation.general_web_enabled,
            str(self._settings.get("web.city", "")),
            str(self._settings.get("pet.live2d_model", "") or ""),
            bool(self._settings.get("pet.bubble", True)),
            str(self._settings.get("interface.theme", "auto")),
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
        self._set_shortcuts(False)
        self._bubble.close()
        self._chat_window.close()
        self._activity.shutdown()
        self._comments.shutdown()
        self._listen.shutdown()
        self._speech.shutdown()
        self._resources.shutdown()
        self._pet.animator.shutdown()


def main() -> int:
    user_dir = data_dir()
    setup_logging(user_dir)
    app = QApplication(sys.argv)
    app.setApplicationName("Kasane Teto AI")
    app.setQuitOnLastWindowClosed(False)

    if DIAGNOSTICS_FLAG in sys.argv:
        from kasane_teto.core import diagnostics

        settings = Settings(default_config_path(), user_dir / "settings.json")
        return 0 if diagnostics.run(settings, user_dir) else 1

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

    started_at = time.time()
    restart = {"requested": False}

    def on_activated() -> None:
        if not is_frozen() and code_changed_since(started_at, project_root()):
            log.info("Hay código nuevo: se reinicia la app")
            restart["requested"] = True
            app.quit()
        else:
            teto.show_pet()

    instance.activated.connect(on_activated)
    teto.start()
    log.info("App iniciada; estado inicial %s", PetState.IDLE.value)
    code = app.exec()
    instance.release()
    if restart["requested"]:
        relaunch(project_root())
    return code


if __name__ == "__main__":
    sys.exit(main())
