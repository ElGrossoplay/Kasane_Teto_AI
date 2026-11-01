"""Bus de eventos de la app: los componentes se comunican por señales Qt."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, Signal

from kasane_teto.character.states import PetState


class EventBus(QObject):
    pet_state_requested = Signal(PetState)
    pet_visibility_toggled = Signal()
    always_on_top_requested = Signal(bool)
    always_on_top_changed = Signal(bool)
    scale_requested = Signal(int)
    scale_changed = Signal(int)
    pack_requested = Signal(str)
    context_menu_requested = Signal(QPoint)
    settings_requested = Signal()
    quit_requested = Signal()
    chat_requested = Signal()
    ai_unload_requested = Signal()
    user_message = Signal(str)
    generation_stop_requested = Signal()
    assistant_status = Signal(str)
    assistant_token = Signal(str)
    assistant_done = Signal()
    assistant_error = Signal(str)
    assistant_notice = Signal(str)
    speech_active = Signal(bool)
    speech_stop_requested = Signal()
    tts_enabled_requested = Signal(bool)
    mic_enabled_requested = Signal(bool)
    volume_requested = Signal(int)
    voice_model_requested = Signal(str)
    web_enabled_requested = Signal(bool)
    history_enabled_requested = Signal(bool)
    memory_suggestions_requested = Signal(bool)
    memory_panel_requested = Signal()
    memory_proposed = Signal(str)
    memory_answered = Signal(bool)
    listen_toggled = Signal()
    listen_started = Signal()
    listen_stopped = Signal()
    transcript_ready = Signal(str)
    voice_status = Signal(str)
