import os
import time

from kasane_teto.core import updates
from kasane_teto.core.paths import project_root
from kasane_teto.core.updates import code_changed_since, relaunch


def make_project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "config").mkdir()
    code = tmp_path / "src" / "a.py"
    code.write_text("x = 1")
    os.utime(code, (1000, 1000))
    return code


def test_old_code_does_not_restart(tmp_path):
    make_project(tmp_path)
    assert not code_changed_since(2000, tmp_path)


def test_new_code_restarts(tmp_path):
    code = make_project(tmp_path)
    os.utime(code, (3000, 3000))
    assert code_changed_since(2000, tmp_path)


def test_other_files_do_not_restart(tmp_path):
    make_project(tmp_path)
    other = tmp_path / "src" / "cache.pyc"
    other.write_text("x")
    os.utime(other, (3000, 3000))
    assert not code_changed_since(2000, tmp_path)


def test_missing_folders_are_ignored(tmp_path):
    assert not code_changed_since(0, tmp_path)


def test_real_project_is_not_newer_than_the_future():
    assert not code_changed_since(time.time() + 3600, project_root())


def test_relaunch_runs_the_launcher_without_a_shell(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    relaunch(tmp_path)
    assert calls[0][0][1] == str(tmp_path / "ejecutar.pyw")
    assert "shell" not in calls[0][1]


def test_failed_relaunch_does_not_crash(monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise OSError("no")

    monkeypatch.setattr(updates.subprocess, "Popen", broken)
    relaunch(tmp_path)
