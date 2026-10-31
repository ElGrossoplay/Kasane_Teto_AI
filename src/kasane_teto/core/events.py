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
