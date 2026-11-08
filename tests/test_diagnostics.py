from kasane_teto.core import diagnostics


def test_report_lists_every_piece_without_loading_the_ai(qapp, settings, tmp_path):
    ok = diagnostics.run(settings, tmp_path, ask_ai=False)
    report = (tmp_path / diagnostics.REPORT_NAME).read_text(encoding="utf-8")
    for label in ("llama-server", "Modelo de GPU", "Python de Piper", "Modelo de Whisper",
                  "Prompt de Teto", "Plantilla de PowerPoint", "Sombreadores de Live2D"):
        assert label in report
    assert report.strip().endswith("todo correcto") is ok


def test_missing_files_are_reported(qapp, settings, tmp_path):
    settings.set("ai.gpu_model", "no-existe.gguf")
    assert diagnostics.run(settings, tmp_path, ask_ai=False) is False
    assert "FALTA Modelo de GPU" in (tmp_path / diagnostics.REPORT_NAME).read_text(encoding="utf-8")
