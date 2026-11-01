from pathlib import Path

from kasane_teto.core.events import EventBus
from kasane_teto.interface.settings_window import SettingsWindow, VoiceOptions


def make_window(bus, web_enabled):
    voice = VoiceOptions(True, ["voz"], "voz", 80, False)
    return SettingsWindow(bus, True, 100, ["provisional"], "provisional", Path("."), voice, web_enabled)


def test_web_checkbox_shows_state_and_requests_change(qapp):
    bus = EventBus()
    requested = []
    bus.web_enabled_requested.connect(requested.append)
    window = make_window(bus, False)
    assert not window._web.isChecked()
    window._web.setChecked(True)
    assert requested == [True]
    window.close()


def test_web_checkbox_explains_what_is_sent(qapp):
    window = make_window(EventBus(), True)
    assert window._web.isChecked()
    assert "nunca la conversación" in window._web.toolTip()
    window.close()
