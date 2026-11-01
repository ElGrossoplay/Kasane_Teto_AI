from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent

from kasane_teto.core.events import EventBus
from kasane_teto.interface.settings_window import SettingsWindow, VoiceOptions


def make_window(bus, web_enabled):
    voice = VoiceOptions(True, ["voz"], "voz", 80, False)
    return SettingsWindow(bus, True, 100, ["provisional"], "provisional", Path("."), voice, web_enabled)


def close(window):
    """La ventana se borra sola al cerrarse: pendiente, Qt la borraría en otra prueba y caería."""
    window.close()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_web_checkbox_shows_state_and_requests_change(qapp):
    bus = EventBus()
    requested = []
    bus.web_enabled_requested.connect(requested.append)
    window = make_window(bus, False)
    assert not window._web.isChecked()
    window._web.setChecked(True)
    assert requested == [True]
    close(window)


def test_comments_checkbox_and_minutes_request_changes(qapp):
    bus = EventBus()
    enabled, minutes = [], []
    bus.comments_enabled_requested.connect(enabled.append)
    bus.comments_minutes_requested.connect(minutes.append)
    window = make_window(bus, False)
    window._comments.setChecked(True)
    window._comment_minutes.setValue(3)
    assert enabled == [True]
    assert minutes == [3]
    close(window)


def test_web_checkbox_explains_what_is_sent(qapp):
    window = make_window(EventBus(), True)
    assert window._web.isChecked()
    assert "nunca la conversación" in window._web.toolTip()
    close(window)
