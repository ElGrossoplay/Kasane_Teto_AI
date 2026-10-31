import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings(tmp_path):
    from kasane_teto.core.paths import default_config_path
    from kasane_teto.core.settings import Settings

    return Settings(default_config_path(), tmp_path / "settings.json")


@pytest.fixture
def pack():
    from kasane_teto.character.pack import load_pack
    from kasane_teto.core.paths import character_root

    return load_pack(character_root() / "provisional")
