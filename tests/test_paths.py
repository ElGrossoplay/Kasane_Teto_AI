import sys

from kasane_teto.core import paths


def test_development_paths_point_to_the_repository():
    root = paths.project_root()
    assert (root / "config" / "default.toml").exists()
    assert paths.models_dir() == root / "models"


def test_packaged_app_reads_resources_inside_and_models_outside(tmp_path, monkeypatch):
    project = tmp_path / "proyecto"
    exe_dir = project / "dist" / "KasaneTetoAI"
    internal = exe_dir / "_internal"
    for folder in (internal / "assets" / "character", project / "models", project / "assets"):
        folder.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "KasaneTetoAI.exe"))
    assert paths.project_root() == internal
    assert paths.default_config_path() == internal / "config" / "default.toml"
    assert paths.models_dir() == project / "models"
    assert paths.character_root() == project / "assets" / "character"


def test_packaged_app_without_project_folder_uses_its_own_assets(tmp_path, monkeypatch):
    exe_dir = tmp_path / "KasaneTetoAI"
    internal = exe_dir / "_internal"
    (internal / "assets").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "KasaneTetoAI.exe"))
    assert paths.knowledge_root() == internal / "assets" / "knowledge"
    assert paths.models_dir() == exe_dir / "models"
