import random

import pytest

from kasane_teto.character.motion import (
    CHANNELS,
    CURSOR_REST_SECONDS,
    ENTRY_GESTURES,
    GESTURES,
    IDLE_FIDGETS,
    POSTURES,
    MotionDirector,
    gesture_duration,
    gesture_pose,
)
from kasane_teto.character.states import PetState
from kasane_teto.desktop.live2d_animator import INPUT_PARAMS, OVERLAY_PARAMS, resolve_params

STEP = 1 / 30


def run(director, seconds, **kwargs):
    pose = {}
    for _ in range(round(seconds / STEP)):
        pose = director.update(STEP, **kwargs)
    return pose


@pytest.fixture
def director():
    return MotionDirector(random.Random(7))


def test_every_state_has_a_posture_and_every_pose_uses_known_channels():
    assert set(POSTURES) == set(PetState)
    poses = [p.pose for p in POSTURES.values()]
    poses += [pose for frames in GESTURES.values() for _time, pose in frames]
    assert all(set(pose) <= set(CHANNELS) for pose in poses)


def test_gestures_start_and_end_at_rest_and_named_ones_exist():
    for name, frames in GESTURES.items():
        assert frames[0] == (0.0, {}) and frames[-1][1] == {}, name
        assert gesture_pose(name, 0.0) == {} and gesture_pose(name, gesture_duration(name)) == {}
        assert [t for t, _ in frames] == sorted(t for t, _ in frames)
    assert {*ENTRY_GESTURES.values(), *IDLE_FIDGETS} <= set(GESTURES)


def test_pose_stays_in_range_whatever_happens(director):
    director.set_state(PetState.HAPPY)
    director.play("stretch")
    for _ in range(200):
        pose = director.update(STEP, cursor=(5.0, -5.0), mouth=1.0, drag_speed=50.0)
        assert set(pose) == set(CHANNELS)
        assert all(-1.0 <= value <= 1.0 for value in pose.values())
        assert pose["lean"] >= 0 and pose["eyes_closed"] >= 0


def test_idle_is_never_still(director):
    """Lo que pidió Diego: que el cuerpo se mueva, no solo la cara."""
    seen = [run(director, 0.5) for _ in range(8)]
    assert max(p["head_z"] for p in seen) - min(p["head_z"] for p in seen) > 0.05
    assert max(p["head_x"] for p in seen) - min(p["head_x"] for p in seen) > 0.03


def test_state_changes_the_body_and_plays_its_gesture(director):
    director.set_state(PetState.HAPPY)
    assert director.gesture == "hop"
    pose = run(director, 2.0)
    assert pose["smile"] > 0.8 and pose["arm_r"] > 0.3
    director.set_state(PetState.CONFUSED)
    assert run(director, 2.0)["head_z"] > 0.4


def test_gesture_moves_the_arms_and_then_ends(director):
    director.play("wave")
    assert run(director, 0.3)["arm_r"] > 0.8
    run(director, gesture_duration("wave"))
    assert director.gesture is None
    with pytest.raises(KeyError):
        director.play("no existe")


def test_follows_a_moving_cursor_and_ignores_a_resting_one(director):
    pose = {}
    for step in range(60):
        pose = director.update(STEP, cursor=(0.9 + 0.001 * step * 30, 0.0))
    assert pose["head_x"] > 0.3 and pose["eye_x"] > 0.5
    resting = run(director, CURSOR_REST_SECONDS + 3.0, cursor=(1.0, 0.0))
    assert abs(resting["eye_x"]) < 0.1


def test_dragging_tilts_her_against_the_movement(director):
    right = run(director, 0.6, drag_speed=1.5)
    assert right["head_z"] < -0.4 and right["arm_r"] > 0.3 and right["foot"] > 0.3
    assert director.lively
    assert abs(run(director, 2.0)["foot"]) < 0.05


def test_talking_bobs_the_head(director):
    quiet = run(director, 1.0)["head_y"]
    director2 = MotionDirector(random.Random(7))
    loud = run(director2, 1.0, mouth=1.0)["head_y"]
    assert loud > quiet + 0.05


def test_fidgets_on_her_own_only_when_calm(director):
    played = set()
    for _ in range(round(120 / STEP)):
        director.update(STEP)
        if director.gesture:
            played.add(director.gesture)
    assert played and played <= set(IDLE_FIDGETS)
    busy = MotionDirector(random.Random(7))
    busy.set_state(PetState.THINKING)
    assert all(busy.update(STEP) and busy.gesture is None for _ in range(round(60 / STEP)))


def test_drowsy_closes_her_eyes_and_waking_stretches(director):
    director.set_drowsy(True)
    pose = run(director, 2.0)
    assert pose["eyes_closed"] > 0.9 and pose["head_y"] < -0.3
    assert not director.lively
    director.set_drowsy(False)
    assert director.gesture == "stretch"


def test_calm_idle_is_not_lively_but_a_gesture_is(director):
    run(director, 1.0)
    assert not director.lively
    director.poke()
    assert director.lively


def test_params_use_the_tracking_inputs_when_the_model_has_them():
    vts = {"ParamAngleXIN", "ParamAngleX", "ParamBrowLYIN", "ParamBrowRYIN", "Param20"}
    assert ("head_x", "ParamAngleXIN", 30.0) in resolve_params(INPUT_PARAMS, vts)
    assert [r for r in resolve_params(INPUT_PARAMS, vts) if r[0] == "brows"] == [
        ("brows", "ParamBrowLYIN", 1.0),
        ("brows", "ParamBrowRYIN", 1.0),
    ]
    assert resolve_params(OVERLAY_PARAMS, vts) == [("arm_r", "Param20", 1.0)]
    plain = {"ParamAngleX", "ParamBrowLY"}
    assert resolve_params(INPUT_PARAMS, plain) == [("head_x", "ParamAngleX", 30.0)]
