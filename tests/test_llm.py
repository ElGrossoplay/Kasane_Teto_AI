import subprocess
import sys
import threading

import psutil
import pytest

from kasane_teto.ai.llm_client import GenerationParams, LLMClient, LLMRequestError, parse_sse_lines
from kasane_teto.ai.llm_process import LLMConfig, LLMProcess, LLMStartError
from kasane_teto.ai.windows_job import KillOnCloseJob


def delta(text):
    return 'data: {"choices":[{"delta":{"content":"%s"}}]}' % text


def config(tmp_path, server="llama-server.exe", model="m.gguf"):
    return LLMConfig(tmp_path / server, tmp_path / model, 4096, 99, 6, 1)


def test_parse_sse_yields_text_until_done():
    lines = [": ping", delta("Ho"), "", delta("la"), "data: [DONE]", delta("nunca")]
    assert list(parse_sse_lines(lines)) == ["Ho", "la"]


def test_parse_sse_skips_invalid_and_empty_chunks():
    lines = ["data: {roto", 'data: {"choices":[{"delta":{}}]}', delta("ok")]
    assert list(parse_sse_lines(lines)) == ["ok"]


def test_parse_sse_reports_finish_reason():
    reasons = []
    lines = [delta("Ho"), 'data: {"choices":[{"delta":{},"finish_reason":"length"}]}']
    assert list(parse_sse_lines(lines, reasons.append)) == ["Ho"]
    assert reasons == ["length"]


def test_args_bind_to_loopback_without_shell_string(tmp_path):
    args = LLMProcess(config(tmp_path), tmp_path / "l.log").build_args(1234, "clave")
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--api-key") + 1] == "clave"
    assert "--no-webui" in args
    assert all(isinstance(arg, str) for arg in args)


def test_missing_server_is_reported(tmp_path):
    with pytest.raises(LLMStartError, match="llama-server.exe"):
        LLMProcess(config(tmp_path), tmp_path / "l.log").start()


def test_missing_model_is_reported(tmp_path):
    (tmp_path / "llama-server.exe").write_bytes(b"x")
    with pytest.raises(LLMStartError, match="m.gguf"):
        LLMProcess(config(tmp_path), tmp_path / "l.log").start()


def test_stop_without_start_is_harmless(tmp_path):
    process = LLMProcess(config(tmp_path), tmp_path / "l.log")
    process.stop()
    assert not process.is_running


def test_connection_error_becomes_request_error():
    client = LLMClient("http://127.0.0.1:1", "k")
    with pytest.raises(LLMRequestError):
        list(client.stream_chat([], GenerationParams(10, 0.5), threading.Event()))


def test_job_kills_child_when_owner_dies():
    owner_code = (
        "import subprocess, sys, time\n"
        "sys.path.insert(0, 'src')\n"
        "from kasane_teto.ai.windows_job import KillOnCloseJob\n"
        "job = KillOnCloseJob()\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "job.assign(int(child._handle))\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    owner = subprocess.Popen([sys.executable, "-c", owner_code], stdout=subprocess.PIPE, text=True)
    child = psutil.Process(int(owner.stdout.readline()))
    assert child.is_running()
    child.parent().kill()
    gone, alive = psutil.wait_procs([child], timeout=5)
    owner.kill()
    for process in alive:
        process.kill()
    assert gone


def test_job_can_be_created():
    assert KillOnCloseJob() is not None
