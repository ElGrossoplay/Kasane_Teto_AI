from PySide6.QtCore import QCoreApplication, QElapsedTimer
from PySide6.QtTest import QSignalSpy

from kasane_teto.core.single_instance import SingleInstance


def test_second_instance_is_refused_and_notifies_first(qapp, tmp_path):
    first = SingleInstance(tmp_path)
    second = SingleInstance(tmp_path)
    assert first.acquire()
    spy = QSignalSpy(first.activated)
    assert not second.acquire()

    timer = QElapsedTimer()
    timer.start()
    while spy.count() == 0 and timer.elapsed() < 2000:
        QCoreApplication.processEvents()
    assert spy.count() == 1
    first.release()


def test_lock_is_available_after_release(qapp, tmp_path):
    first = SingleInstance(tmp_path)
    assert first.acquire()
    first.release()
    second = SingleInstance(tmp_path)
    assert second.acquire()
    second.release()
