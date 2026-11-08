import json
import random
from pathlib import Path

import pytest
from PIL import Image

from kasane_teto.core.events import EventBus
from kasane_teto.desktop.animator import SpriteAnimator
from kasane_teto.desktop.live2d_animator import (
    STATE_EXPRESSIONS,
    WATERMARK_EXPRESSION,
    Live2DAnimator,
    mouth_opening,
    reduced_textures,
)
from kasane_teto.desktop.pet_window import PetWindow

REAL_MODEL = Path(r"E:\重音テト\VTS Model File\重音テト\重音テト.model3.json")


def fake_model(folder: Path, side: int = 64) -> Path:
    (folder / "tex").mkdir(parents=True)
    Image.new("RGBA", (side, side), (255, 0, 0, 255)).save(folder / "tex" / "texture_00.png")
    model = folder / "modelo.model3.json"
    model.write_text(json.dumps({"FileReferences": {"Textures": ["tex/texture_00.png"]}}), encoding="utf-8")
    return model


def test_textures_are_reduced_into_the_local_cache_only(tmp_path):
    model = fake_model(tmp_path / "modelo", side=64)
    paths = reduced_textures(model, tmp_path / "cache", side=32)
    assert Path(paths[0]).is_relative_to(tmp_path / "cache")
    assert Image.open(paths[0]).size == (32, 32)
    assert Image.open(model.parent / "tex" / "texture_00.png").size == (64, 64)


def test_reduced_textures_are_reused_and_redone_when_the_model_changes(tmp_path):
    model = fake_model(tmp_path / "modelo", side=64)
    first = reduced_textures(model, tmp_path / "cache", side=32)
    assert reduced_textures(model, tmp_path / "cache", side=32) == first
    Image.new("RGBA", (64, 64), (0, 0, 255, 255)).save(model.parent / "tex" / "texture_00.png")
    assert reduced_textures(model, tmp_path / "cache", side=32) != first


def test_reduction_does_not_mix_hidden_colours(tmp_path):
    """El modelo guarda color en zonas invisibles: mezclarlo dibuja halos."""
    folder = tmp_path / "modelo"
    model = fake_model(folder, side=4)
    image = Image.new("RGBA", (4, 4), (0, 255, 0, 0))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.save(folder / "tex" / "texture_00.png")
    reduced = Image.open(reduced_textures(model, tmp_path / "cache", side=2)[0])
    assert set(reduced.getdata()) <= {(255, 0, 0, 255), (0, 255, 0, 0)}


def test_mouth_moves_within_range():
    rng = random.Random(1)
    values = [mouth_opening(t / 30, rng) for t in range(90)]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert max(values) - min(values) > 0.5


def test_mapped_expressions_exist_in_the_real_model():
    if not REAL_MODEL.exists():
        pytest.skip("Modelo de Diego no disponible")
    names = {p.name.removesuffix(".exp3.json") for p in (REAL_MODEL.parent / "Expressions").glob("*.exp3.json")}
    used = {WATERMARK_EXPRESSION, *(n for group in STATE_EXPRESSIONS.values() for n in group)}
    assert used <= names


def test_pet_window_switches_animator_and_keeps_its_place(qapp, pack, settings, tmp_path):
    sprites = SpriteAnimator(pack)
    pet = PetWindow(sprites, settings, EventBus())
    pet.move(300, 300)
    bottom = pet.geometry().bottom()
    live = Live2DAnimator(fake_model(tmp_path / "m"), tmp_path / "cache")
    pet.set_animator(live)
    assert pet.animator is live
    assert pet.size() == live.base_size()
    assert pet.geometry().bottom() == bottom
    pet.set_animator(sprites)
    assert pet.size() == sprites.base_size()
    pet.close()


REAL_CHECK = """
import sys
from pathlib import Path
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from kasane_teto.character.states import PetState
from kasane_teto.desktop.live2d_animator import Live2DAnimator
app = QApplication([])
animator = Live2DAnimator(Path(sys.argv[1]), Path(sys.argv[2]))
errors = []
animator.failed.connect(errors.append)
animator.set_render_size(QSize(240, 560))
animator.start()
for _ in range(10):
    animator._tick()
image = animator.current_pixmap().toImage()
assert errors == [], errors
assert image.size() == QSize(240, 560), image.size()
assert image.pixelColor(2, 2).alpha() == 0
assert image.pixelColor(120, 120).alpha() == 255
animator.set_state(PetState.SURPRISED)
animator._tick()
animator.set_pace(still=True)
assert animator._context is None and not animator.is_animating
assert not animator.current_pixmap().isNull()
animator.shutdown()
print("LIVE2D OK")
"""


@pytest.mark.slow
def test_real_model_draws_with_transparency_and_releases(tmp_path):
    """En otro proceso: las pruebas usan Qt sin pantalla, y ahí no hay OpenGL."""
    import os
    import subprocess
    import sys

    if not REAL_MODEL.exists():
        pytest.skip("Modelo de Diego no disponible")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", REAL_CHECK, str(REAL_MODEL), str(tmp_path / "cache")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120,
    )
    assert "LIVE2D OK" in result.stdout, result.stderr[-2000:]
