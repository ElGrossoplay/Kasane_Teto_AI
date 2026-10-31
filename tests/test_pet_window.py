import pytest

from kasane_teto.core.events import EventBus
from kasane_teto.desktop.animator import SpriteAnimator
from kasane_teto.desktop.pet_window import MAX_SCALE, MIN_SCALE, PetWindow


@pytest.fixture
def window(qapp, pack, settings):
    pet = PetWindow(SpriteAnimator(pack), settings, EventBus())
    yield pet
    pet.close()


def test_scale_changes_size_and_persists(window, settings):
    width = window.width()
    window.set_scale(200)
    assert window.width() == width * 2
    assert settings.get("pet.scale") == 200


def test_scale_is_clamped(window):
    window.set_scale(10_000)
    assert window.scale_percent == MAX_SCALE
    window.set_scale(-5)
    assert window.scale_percent == MIN_SCALE


def test_resize_keeps_bottom_center(window):
    window.move(window.screen().availableGeometry().center())
    window.move(window.x() - 200, window.y() - 100)
    before = window.geometry()
    window.set_scale(150)
    after = window.geometry()
    assert after.bottom() == before.bottom()
    assert abs(after.center().x() - before.center().x()) <= 1


def test_resize_near_screen_edge_stays_on_screen(window):
    area = window.screen().availableGeometry()
    window.move(area.right() - window.width() + 1, area.bottom() - window.height() + 1)
    window.set_scale(150)
    assert area.contains(window.geometry())


def test_always_on_top_persists(window, settings):
    window.set_always_on_top(False)
    assert not window.always_on_top
    assert settings.get("pet.always_on_top") is False


def test_position_is_restored(qapp, pack, settings):
    settings.set("pet.x", 100)
    settings.set("pet.y", 120)
    pet = PetWindow(SpriteAnimator(pack), settings, EventBus())
    assert (pet.x(), pet.y()) == (100, 120)


def test_offscreen_position_is_discarded(qapp, pack, settings):
    settings.set("pet.x", 99_999)
    settings.set("pet.y", 99_999)
    pet = PetWindow(SpriteAnimator(pack), settings, EventBus())
    assert pet.x() != 99_999


def test_animation_stops_while_hidden(window):
    window.show()
    assert window._animator._timer.isActive()
    window.hide()
    assert not window._animator._timer.isActive()
