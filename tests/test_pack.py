import pytest

from kasane_teto.character.pack import PackError, list_packs, load_pack
from kasane_teto.character.states import PetState


def write_pack(root, body, frames=("idle.png",)):
    root.mkdir()
    (root / "manifest.toml").write_text(body, encoding="utf-8")
    for frame in frames:
        (root / frame).write_bytes(b"x")
    return root


def test_provisional_pack_has_every_state(pack):
    assert set(pack.animations) == set(PetState)


def test_missing_state_falls_back_to_idle(tmp_path):
    root = write_pack(tmp_path / "p", '[states.idle]\nframes = ["idle.png"]\n')
    loaded = load_pack(root)
    assert loaded.animation(PetState.ANGRY) == loaded.animations[PetState.IDLE]


def test_idle_is_required(tmp_path):
    root = write_pack(tmp_path / "p", '[states.happy]\nframes = ["idle.png"]\n')
    with pytest.raises(PackError):
        load_pack(root)


def test_frame_outside_pack_is_rejected(tmp_path):
    (tmp_path / "secreto.png").write_bytes(b"x")
    root = write_pack(tmp_path / "p", '[states.idle]\nframes = ["../secreto.png"]\n')
    with pytest.raises(PackError, match="fuera del paquete"):
        load_pack(root)


def test_missing_frame_is_rejected(tmp_path):
    root = write_pack(tmp_path / "p", '[states.idle]\nframes = ["no.png"]\n')
    with pytest.raises(PackError, match="no encontrado"):
        load_pack(root)


def test_invalid_fps_is_rejected(tmp_path):
    root = write_pack(tmp_path / "p", '[states.idle]\nframes = ["idle.png"]\nfps = 0\n')
    with pytest.raises(PackError, match="fps"):
        load_pack(root)


def test_broken_manifest_is_rejected(tmp_path):
    root = write_pack(tmp_path / "p", "esto no es toml =")
    with pytest.raises(PackError):
        load_pack(root)


def test_unknown_state_is_ignored(tmp_path):
    root = write_pack(
        tmp_path / "p",
        '[states.idle]\nframes = ["idle.png"]\n[states.bailando]\nframes = ["idle.png"]\n',
    )
    assert set(load_pack(root).animations) == {PetState.IDLE}


def test_list_packs_only_includes_folders_with_manifest(tmp_path):
    write_pack(tmp_path / "a", '[states.idle]\nframes = ["idle.png"]\n')
    (tmp_path / "b").mkdir()
    assert list_packs(tmp_path) == ["a"]
    assert list_packs(tmp_path / "no_existe") == []
