import array
import sys
import time

import pytest
from PySide6.QtCore import QCoreApplication, QElapsedTimer

from kasane_teto.character.states import PetState
from kasane_teto.core.events import EventBus
from kasane_teto.memory.knowledge import Entry, KnowledgeBase
from kasane_teto.voice.audio import SILENCE_PEAK, Recording, apply_volume, is_silence
from kasane_teto.voice.listening import ListenService
from kasane_teto.voice.speech import SentenceSplitter, SpeechService, clean_for_speech
from kasane_teto.voice.worker_process import VoiceError, WorkerProcess


def pump(condition, timeout_ms=3000):
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < timeout_ms:
        QCoreApplication.processEvents()
        time.sleep(0.002)
    assert condition()


def loud(seconds=1.0):
    return array.array("h", [SILENCE_PEAK * 2] * int(16000 * seconds)).tobytes()


def test_splitter_emits_complete_sentences_as_they_arrive():
    splitter = SentenceSplitter()
    assert splitter.feed("Hola, ¿qué") == []
    assert splitter.feed(" tal? Yo bien") == ["Hola, ¿qué tal?"]
    assert splitter.flush() == ["Yo bien"]
    assert splitter.flush() == []


def test_splitter_keeps_decimals_together():
    splitter = SentenceSplitter()
    assert splitter.feed("Mide 1.5 metros. Fin ") == ["Mide 1.5 metros."]


def test_splitter_cuts_on_newlines():
    assert SentenceSplitter().feed("Primera\nSegunda\n") == ["Primera", "Segunda"]


def test_clean_removes_markup_and_empty_text():
    assert clean_for_speech("*Hola*  `mundo`~") == "Hola mundo"
    assert clean_for_speech("*** ...") == ""


def test_volume_scales_samples():
    pcm = array.array("h", [1000, -1000]).tobytes()
    assert array.array("h", apply_volume(pcm, 50)).tolist() == [500, -500]
    assert apply_volume(pcm, 100) == pcm


def test_recording_duration_accounts_for_channels():
    pcm = bytes(48000 * 2 * 2)
    assert Recording(pcm, 48000, 2).seconds == 1.0


def test_silence_detection():
    assert is_silence(b"")
    assert is_silence(array.array("h", [10, -10]).tobytes())
    assert not is_silence(loud(0.1))


def worker(code):
    return WorkerProcess([sys.executable, "-c", code])


def test_worker_reports_ready_data():
    process = worker("import sys; print('{\"sample_rate\": 8000}', file=sys.stderr, flush=True); sys.stdin.read()")
    assert process.start() == {"sample_rate": 8000}
    assert process.is_running
    process.stop()
    assert not process.is_running


def test_worker_ignores_log_lines_before_ready():
    process = worker("import sys; print('aviso', file=sys.stderr); print('{\"ok\": 1}', file=sys.stderr, flush=True); sys.stdin.read()")
    assert process.start() == {"ok": 1}
    process.stop()


def test_worker_that_dies_raises_voice_error():
    with pytest.raises(VoiceError):
        worker("raise SystemExit(1)").start()


def test_missing_program_raises_voice_error():
    with pytest.raises(VoiceError):
        WorkerProcess(["D:/no/existe.exe"]).start()


class FakeTTS:
    sample_rate = 8000

    def __init__(self, delay=0.0, error=None):
        self.said = []
        self.unloaded = 0
        self.delay = delay
        self.error = error

    def synthesize(self, text, length_scale):
        if self.error:
            raise self.error
        self.said.append(text)
        time.sleep(self.delay)
        yield b"\x00\x00"

    def unload(self):
        self.unloaded += 1


class FakePlayer:
    def __init__(self):
        self.played = 0

    def play(self, pcm, rate, volume, cancel):
        self.played += 1

    def close(self):
        pass


@pytest.fixture
def speech(qapp, settings):
    made = []

    def make(engine=None):
        bus = EventBus()
        engine = engine or FakeTTS()
        service = SpeechService(bus, settings, engine, FakePlayer())
        states = []
        bus.speech_active.connect(states.append)
        made.append(service)
        return bus, service, engine, states

    yield make
    for service in made:
        service.shutdown()


def test_answer_is_spoken_in_order_then_goes_idle(speech):
    bus, _, engine, states = speech()
    bus.assistant_token.emit("Primera frase. Segunda")
    bus.assistant_token.emit(" frase.")
    bus.assistant_done.emit()
    pump(lambda: states == [True, False])
    assert engine.said == ["Primera frase.", "Segunda frase."]


def test_disabled_voice_stays_silent(speech, settings):
    settings.set("voice.tts_enabled", False)
    bus, _, engine, states = speech()
    bus.assistant_token.emit("Hola.  ")
    bus.assistant_done.emit()
    time.sleep(0.05)
    QCoreApplication.processEvents()
    assert engine.said == [] and states == []


def test_new_message_discards_pending_speech(speech):
    bus, _, engine, states = speech(FakeTTS(delay=0.05))
    bus.assistant_token.emit("Una. Dos. Tres. Cuatro. ")
    pump(lambda: engine.said)
    bus.user_message.emit("otra cosa")
    bus.assistant_token.emit("Nueva. ")
    bus.assistant_done.emit()
    pump(lambda: "Nueva." in engine.said)
    assert "Cuatro." not in engine.said


def test_voice_failure_does_not_break_the_turn(speech):
    bus, _, _, states = speech(FakeTTS(error=VoiceError("sin voz")))
    bus.assistant_token.emit("Hola. ")
    bus.assistant_done.emit()
    pump(lambda: states and states[-1] is False)


def test_changing_voice_unloads_the_previous_one(speech):
    bus, service, old, _ = speech()
    new = FakeTTS()
    service.set_engine(new)
    bus.assistant_token.emit("Hola. ")
    pump(lambda: new.said == ["Hola."])
    assert old.unloaded == 1


class FakeRecorder:
    def __init__(self, pcm=None, error=None):
        self.pcm = loud() if pcm is None else pcm
        self.error = error
        self.started = 0

    def start(self):
        if self.error:
            raise self.error
        self.started += 1

    def stop(self):
        return Recording(self.pcm, 16000, 1)


class FakeSTT:
    def __init__(self, text="hola", error=None):
        self.text = text
        self.error = error
        self.audio = []
        self.unloaded = 0

    def transcribe(self, recording):
        self.audio.append(recording)
        if self.error:
            raise self.error
        return self.text

    def unload(self):
        self.unloaded += 1


@pytest.fixture
def listen(qapp, settings):
    made = []

    def make(stt=None, recorder=None, enabled=True):
        settings.set("voice.mic_enabled", enabled)
        bus = EventBus()
        stt = stt or FakeSTT()
        recorder = recorder or FakeRecorder()
        service = ListenService(bus, settings, stt, recorder)
        log = {"text": [], "status": [], "states": []}
        bus.transcript_ready.connect(log["text"].append)
        bus.voice_status.connect(log["status"].append)
        bus.pet_state_requested.connect(log["states"].append)
        made.append(service)
        return bus, service, stt, recorder, log

    yield make
    for service in made:
        service.shutdown()


def test_toggle_records_and_transcribes(listen):
    bus, service, stt, _, log = listen()
    bus.listen_toggled.emit()
    assert service.is_recording
    assert log["states"] == [PetState.LISTENING]
    bus.listen_toggled.emit()
    pump(lambda: log["text"] == ["hola"])
    assert not service.is_recording
    assert stt.audio


def test_microphone_off_never_records(listen):
    bus, service, _, recorder, log = listen(enabled=False)
    bus.listen_toggled.emit()
    assert not service.is_recording
    assert recorder.started == 0
    assert "apagado" in log["status"][-1]


def test_listening_interrupts_speech(listen):
    bus, _, _, _, _ = listen()
    stops = []
    bus.speech_stop_requested.connect(lambda: stops.append(True))
    bus.listen_started.emit()
    assert stops == [True]


def test_silence_is_not_sent_to_the_recognizer(listen):
    bus, _, stt, _, log = listen(recorder=FakeRecorder(array.array("h", [5] * 16000).tobytes()))
    bus.listen_started.emit()
    bus.listen_stopped.emit()
    assert stt.audio == []
    assert log["states"][-1] is PetState.IDLE
    assert "oído" in log["status"][-1]


def test_very_short_press_is_ignored(listen):
    bus, _, stt, _, _ = listen(recorder=FakeRecorder(loud(0.1)))
    bus.listen_started.emit()
    bus.listen_stopped.emit()
    assert stt.audio == []


def test_unusable_microphone_shows_message(listen):
    bus, service, _, _, log = listen(recorder=FakeRecorder(error=VoiceError("x")))
    bus.listen_started.emit()
    assert not service.is_recording
    assert "micrófono" in log["status"][-1]


def test_recognizer_failure_returns_to_idle(listen):
    bus, _, _, _, log = listen(stt=FakeSTT(error=VoiceError("x")))
    bus.listen_started.emit()
    bus.listen_stopped.emit()
    pump(lambda: log["states"][-1] is PetState.IDLE)
    assert log["text"] == []


def test_turning_off_microphone_stops_recording_and_unloads(listen):
    bus, service, stt, _, _ = listen()
    bus.listen_started.emit()
    bus.mic_enabled_requested.emit(False)
    assert not service.is_recording
    pump(lambda: stt.unloaded == 1)


def test_vocabulary_lists_names_within_limit():
    base = KnowledgeBase([Entry("a", ("Hatsune Miku", "miku"), "h", ""), Entry("b", ("UTAU",), "h", "")])
    assert base.vocabulary().endswith("Kikuo, Hatsune Miku, UTAU")
    assert base.vocabulary(max_chars=15) == "Kasane Teto"
