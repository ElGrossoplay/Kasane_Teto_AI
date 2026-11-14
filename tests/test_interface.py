"""Bocadillo, tema, manejo de la mascota con el ratón y mejoras del chat."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from kasane_teto.core.events import EventBus
from kasane_teto.desktop.animator import SpriteAnimator
from kasane_teto.desktop.bubble import MAX_CHARS, MAX_SECONDS, SpeechBubble, reading_seconds, visible_tail
from kasane_teto.desktop.hotkey import CHAT, SHOW, TALK
from kasane_teto.desktop.pet_window import DRAG_THRESHOLD, PetWindow
from kasane_teto.desktop.tray import GESTURE_LABELS
from kasane_teto.character.motion import GESTURES
from kasane_teto.interface import theme
from kasane_teto.interface.chat_window import READY_STATUS, ChatWindow


def mouse(window, kind, button, pos=QPoint(10, 10), buttons=None):
    event = QMouseEvent(
        kind,
        QPointF(pos),
        QPointF(window.mapToGlobal(pos)),
        button,
        button if buttons is None else buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    {
        QEvent.Type.MouseButtonPress: window.mousePressEvent,
        QEvent.Type.MouseButtonRelease: window.mouseReleaseEvent,
        QEvent.Type.MouseMove: window.mouseMoveEvent,
        QEvent.Type.MouseButtonDblClick: window.mouseDoubleClickEvent,
    }[kind](event)


class Recorder(SpriteAnimator):
    def __init__(self, pack):
        super().__init__(pack)
        self.pokes = 0
        self.dragged = []

    def poke(self):
        self.pokes += 1

    def note_drag(self, pixels):
        self.dragged.append(pixels)


@pytest.fixture
def pet(qapp, pack, settings):
    bus = EventBus()
    window = PetWindow(Recorder(pack), settings, bus)
    yield window, bus
    window.close()


def test_click_pokes_and_double_click_opens_the_chat(pet):
    window, bus = pet
    chats = []
    bus.chat_requested.connect(lambda: chats.append(True))
    left = Qt.MouseButton.LeftButton
    mouse(window, QEvent.Type.MouseButtonPress, left)
    mouse(window, QEvent.Type.MouseButtonRelease, left, buttons=Qt.MouseButton.NoButton)
    assert window.animator.pokes == 1 and chats == []
    mouse(window, QEvent.Type.MouseButtonDblClick, left)
    mouse(window, QEvent.Type.MouseButtonRelease, left, buttons=Qt.MouseButton.NoButton)
    assert chats == [True] and window.animator.pokes == 1


def test_a_small_mouse_wobble_is_still_a_click(pet):
    window, _ = pet
    left = Qt.MouseButton.LeftButton
    mouse(window, QEvent.Type.MouseButtonPress, left)
    mouse(window, QEvent.Type.MouseMove, Qt.MouseButton.NoButton, QPoint(10 + DRAG_THRESHOLD - 2, 10), left)
    assert not window._dragging
    mouse(window, QEvent.Type.MouseButtonRelease, left, buttons=Qt.MouseButton.NoButton)
    assert window.animator.pokes == 1


def test_dragging_is_not_a_click_and_tells_the_animator(pet):
    window, _ = pet
    window.show()
    left = Qt.MouseButton.LeftButton
    mouse(window, QEvent.Type.MouseButtonPress, left)
    mouse(window, QEvent.Type.MouseMove, Qt.MouseButton.NoButton, QPoint(10 + DRAG_THRESHOLD * 3, 10), left)
    assert window._dragging
    window.move(window.x() + 40, window.y())
    assert sum(window.animator.dragged) == pytest.approx(40 * window.devicePixelRatioF())
    mouse(window, QEvent.Type.MouseButtonRelease, left, buttons=Qt.MouseButton.NoButton)
    assert window.animator.pokes == 0 and not window._dragging
    window.move(window.x() + 40, window.y())
    assert len(window.animator.dragged) == 1


def test_middle_click_toggles_listening(pet):
    window, bus = pet
    toggles = []
    bus.listen_toggled.connect(lambda: toggles.append(True))
    mouse(window, QEvent.Type.MouseButtonPress, Qt.MouseButton.MiddleButton)
    assert toggles == [True]


def test_bubble_text_keeps_the_end_of_a_long_answer():
    assert visible_tail("  hola  ") == "hola"
    long = "palabra " * 100
    tail = visible_tail(long)
    assert tail.startswith("…palabra") and len(tail) <= MAX_CHARS + 1
    assert reading_seconds("") < reading_seconds("x" * 50) <= MAX_SECONDS
    assert reading_seconds("x" * 5000) == MAX_SECONDS


@pytest.fixture
def bubble(qapp):
    widget = SpeechBubble()
    widget.set_anchor(QRect(400, 400, 200, 400))
    yield widget
    widget.close()


def test_bubble_shows_status_then_answer_above_the_pet(bubble):
    bubble.set_status("Pensando…")
    assert bubble.isVisible() and bubble.text == "Pensando…"
    bubble.append("Hola, ")
    bubble.append("Diego")
    assert bubble.text == "Hola, Diego"
    assert bubble.geometry().bottom() <= 400 + 400 * 0.05
    assert abs(bubble.geometry().center().x() - 500) <= 2
    bubble.finish()
    assert bubble.isVisible() and bubble._hide_timer.isActive()
    bubble.begin()
    assert not bubble.isVisible()


def test_bubble_never_takes_clicks_or_focus(bubble):
    flags = bubble.windowFlags()
    assert flags & Qt.WindowType.WindowTransparentForInput
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def test_bubble_hides_when_blocked_or_disabled_and_follows_on_top(bubble):
    bubble.append("Hola")
    bubble.set_blocked(True)
    assert not bubble.isVisible()
    bubble.set_blocked(False)
    assert bubble.isVisible()
    bubble.set_on_top(False)
    assert not bubble.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    bubble.set_enabled(False)
    bubble.append("otra cosa")
    assert not bubble.isVisible()


def test_bubble_stays_inside_the_screen(bubble):
    area = bubble.screen().availableGeometry()
    bubble.set_anchor(QRect(area.left() - 50, area.top() + 5, 100, 300))
    bubble.say("Un aviso bastante largo para que el bocadillo tenga anchura de sobra.")
    assert bubble.x() >= area.left() and bubble.y() >= area.top()


def test_theme_applies_and_reports_its_colours(qapp):
    before = (qapp.style().objectName(), qapp.palette(), qapp.styleSheet())
    try:
        assert theme.apply_theme(qapp, "claro") is theme.LIGHT and theme.colors() is theme.LIGHT
        assert theme.apply_theme(qapp, "oscuro") is theme.DARK
        assert theme.DARK.accent in qapp.styleSheet()
        assert theme.apply_theme(qapp, "auto") in (theme.DARK, theme.LIGHT)
    finally:
        qapp.setStyle(before[0])
        qapp.setPalette(before[1])
        qapp.setStyleSheet(before[2])


def test_shortcuts_are_distinct_and_menu_gestures_exist():
    assert len({TALK.hotkey_id, CHAT.hotkey_id, SHOW.hotkey_id}) == 3
    assert len({TALK.key, CHAT.key, SHOW.key}) == 3
    assert TALK.label == "Ctrl+Alt+T"
    assert set(GESTURE_LABELS) <= set(GESTURES)


@pytest.fixture
def chat(qapp, settings):
    bus = EventBus()
    window = ChatWindow(bus, settings)
    yield bus, window, settings
    window.close()


def press(window, key):
    return window.eventFilter(
        window._input, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    )


def test_chat_recalls_sent_messages_with_the_arrows(chat):
    bus, window, _ = chat
    for text in ("uno", "dos"):
        window._send_text(text)
        bus.assistant_done.emit()
    assert press(window, Qt.Key.Key_Up) and window._input.text() == "dos"
    assert press(window, Qt.Key.Key_Up) and window._input.text() == "uno"
    press(window, Qt.Key.Key_Up)
    assert window._input.text() == "uno"
    press(window, Qt.Key.Key_Down)
    press(window, Qt.Key.Key_Down)
    assert window._input.text() == ""
    assert not press(window, Qt.Key.Key_A)


def test_chat_status_falls_back_to_ready_and_links_sources(chat):
    bus, window, _ = chat
    bus.assistant_status.emit("Pensando…")
    assert window._status.text() == "Pensando…"
    bus.assistant_done.emit()
    assert window._status.text() == READY_STATUS
    bus.assistant_notice.emit("\n(Datos de VocaDB: https://vocadb.net/Ar/1)")
    assert "https://vocadb.net/Ar/1" in window._log.toPlainText()
    assert 'href="https://vocadb.net/Ar/1"' in window._log.toHtml()


def test_chat_remembers_its_place_and_reports_visibility(qapp, settings):
    window = ChatWindow(EventBus(), settings)
    seen = []
    window.visibility_changed.connect(lambda: seen.append(window.isVisible()))
    area = window.screen().availableGeometry()
    window.setGeometry(area.left() + 60, area.top() + 80, 500, 600)
    window.show()
    window.close()
    assert seen == [True, False]
    saved = settings.get("chat.geometry")
    assert saved[2:] == [500, 600]
    again = ChatWindow(EventBus(), settings)
    assert (again.width(), again.height()) == (500, 600)
    again.close()
    settings.set("chat.geometry", [99_999, 99_999, 500, 600])
    lost = ChatWindow(EventBus(), settings)
    assert lost.x() != 99_999
    lost.close()
