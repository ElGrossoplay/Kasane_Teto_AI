from PySide6.QtTest import QSignalSpy

from kasane_teto.character.states import PetState
from kasane_teto.desktop.animator import SpriteAnimator


def test_set_state_resets_frame_and_notifies(qapp, pack):
    animator = SpriteAnimator(pack)
    spy = QSignalSpy(animator.frame_changed)
    animator._advance()
    assert animator.frame_index == 1
    animator.set_state(PetState.HAPPY)
    assert animator.state is PetState.HAPPY
    assert animator.frame_index == 0
    assert spy.count() == 2


def test_frames_wrap_around(qapp, pack):
    animator = SpriteAnimator(pack)
    animator._advance()
    animator._advance()
    assert animator.frame_index == 0


def test_timer_only_runs_after_start(qapp, pack):
    animator = SpriteAnimator(pack)
    assert not animator._timer.isActive()
    animator.start()
    assert animator._timer.isActive()
    animator.stop()
    assert not animator._timer.isActive()
    animator.set_state(PetState.ANGRY)
    assert not animator._timer.isActive()


def test_every_state_loads_a_pixmap(qapp, pack):
    animator = SpriteAnimator(pack)
    for state in PetState:
        animator.set_state(state)
        assert not animator.current_pixmap().isNull()
