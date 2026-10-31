from kasane_teto.core.paths import default_config_path
from kasane_teto.core.settings import Settings


def test_default_values(settings):
    assert settings.get("pet.scale") == 100
    assert settings.get("pet.x") is None
    assert settings.get("pet.x", 5) == 5


def test_user_value_persists_and_overrides_default(tmp_path):
    path = tmp_path / "settings.json"
    Settings(default_config_path(), path).set("pet.scale", 150)
    reloaded = Settings(default_config_path(), path)
    assert reloaded.get("pet.scale") == 150
    assert reloaded.get("pet.pack") == "provisional"


def test_corrupt_user_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{no es json", encoding="utf-8")
    assert Settings(default_config_path(), path).get("pet.scale") == 100


def test_non_object_user_file_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert Settings(default_config_path(), path).get("pet.scale") == 100
