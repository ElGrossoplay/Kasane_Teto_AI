import pytest

from kasane_teto.core.activity import Activity, ActivityService
from kasane_teto.core.events import EventBus
from kasane_teto.tools.windows_control import Foreground

GAME = Foreground("VALORANT", True)
DESKTOP = Foreground("", False)
BROWSER = Foreground("YouTube - Google Chrome", False)


class World:
    def __init__(self):
        self.now = 0.0
        self.front = BROWSER
        self.game_open = False


@pytest.fixture
def make(qapp, settings):
    created = []

    def build():
        world = World()
        bus = EventBus()
        service = ActivityService(
            bus,
            settings,
            read_foreground=lambda: world.front,
            game_open=lambda: world.game_open,
            clock=lambda: world.now,
        )
        service.shutdown()  # Las pruebas llaman a check() a mano.
        states = []
        service.changed.connect(states.append)
        created.append(service)
        return bus, service, world, states

    return build


def test_game_in_front_twice_enters_game_mode(make):
    _, service, world, states = make()
    world.front = GAME
    service.check()
    assert service.state is Activity.ACTIVE
    service.check()
    assert states == [Activity.GAME]


def test_short_alt_tab_keeps_game_mode(make, settings):
    _, service, world, _ = make()
    world.front = GAME
    service.check()
    service.check()
    world.front, world.game_open = BROWSER, False
    world.now += 10
    service.check()
    assert service.state is Activity.GAME  # todavía no han pasado 30 s sin el juego delante
    world.game_open = True
    world.now += 60
    service.check()
    assert service.state is Activity.GAME  # sigue abierto en otra ventana
    world.game_open = False
    service.check()
    assert service.state is Activity.ACTIVE


def test_desktop_without_title_is_not_a_game(make):
    _, service, world, _ = make()
    world.front = Foreground("", True)
    service.check()
    service.check()
    assert service.state is Activity.ACTIVE


def test_extra_titles_from_settings_count_as_games(make, settings):
    settings.set("game_mode.titles", ["Hollow Knight"])
    _, service, world, _ = make()
    world.front = Foreground("hollow knight", False)
    service.check()
    service.check()
    assert service.state is Activity.GAME


def test_auto_detection_can_be_turned_off(make):
    bus, service, world, _ = make()
    bus.game_mode_auto_requested.emit(False)
    world.front = GAME
    service.check()
    service.check()
    assert service.state is Activity.ACTIVE


def test_turning_game_mode_off_by_hand_is_respected_until_the_game_leaves(make):
    bus, service, world, _ = make()
    world.front = GAME
    service.check()
    service.check()
    bus.game_mode_requested.emit(False)
    service.check()
    service.check()
    assert service.state is Activity.ACTIVE
    world.front = BROWSER
    service.check()
    world.front = GAME
    service.check()
    service.check()
    assert service.state is Activity.GAME


def test_manual_game_mode_ignores_what_is_in_front(make):
    bus, service, world, _ = make()
    bus.game_mode_requested.emit(True)
    world.now += 3600
    service.check()
    assert service.state is Activity.GAME
    bus.game_mode_requested.emit(False)
    assert service.state is Activity.IDLE


def test_idle_after_minutes_and_active_again_on_use(make, settings):
    bus, service, world, states = make()
    world.now += settings.get("pet.idle_minutes") * 60
    service.check()
    assert service.state is Activity.IDLE
    bus.user_message.emit("hola")
    assert states == [Activity.IDLE, Activity.ACTIVE]


def test_suspended_wins_and_talking_wakes_her(make):
    bus, service, world, _ = make()
    bus.game_mode_requested.emit(True)
    bus.suspend_requested.emit(True)
    assert service.state is Activity.SUSPENDED
    world.front = GAME
    service.check()
    assert service.state is Activity.SUSPENDED
    bus.chat_requested.emit()
    assert service.state is Activity.GAME


def test_detection_only_reads_the_foreground_title():
    """Regla de anticheat: ni procesos ni capturas para saber si hay un juego."""
    import inspect

    import kasane_teto.core.activity as activity

    source = inspect.getsource(activity)
    for forbidden in ("psutil", "process_iter", "OpenProcess", "grab", "capture"):
        assert forbidden not in source
