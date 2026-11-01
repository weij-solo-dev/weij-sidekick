import logging

from sidekick.log import Log, configure_logging, mask_secret


def test_mask_secret_shapes():
    assert mask_secret(None) == "<empty>"
    assert mask_secret("") == "<empty>"
    assert mask_secret("short") == "****(5)"
    masked = mask_secret("sk-cp-ABCDEFGHIJKLMNOP1234")
    assert masked.startswith("sk-c") and masked.endswith("1234(26)")
    assert "ABCDEFGH" not in masked


def test_log_lines_carry_module_function_and_entry_marker(tmp_path):
    configure_logging("DEBUG", tmp_path / "logs")
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logging.getLogger("sidekick").addHandler(Capture())
    Log.info0("boot")
    Log.warning("careful")
    entry = [r for r in records if r.getMessage() == "-> boot"]
    assert entry and entry[0].funcName == "test_log_lines_carry_module_function_and_entry_marker"
    assert entry[0].name.startswith("sidekick.")
    assert any(r.levelno == logging.WARNING and r.getMessage() == "careful" for r in records)
    text = (tmp_path / "logs" / "sidekick.log").read_text()
    assert "-> boot" in text and "[W]" in text


def test_configure_logging_is_idempotent(tmp_path):
    configure_logging("INFO", tmp_path / "logs")
    configure_logging("INFO", tmp_path / "logs")
    root = logging.getLogger("sidekick")
    assert len(root.handlers) == 3  # stderr, the file, the in-memory ring of warnings


def test_recent_warnings_ring(tmp_path):
    """Warnings and errors stay in memory for the Live page (block #69); infos do not."""
    configure_logging("INFO", tmp_path / "logs")
    Log.info("nothing to see")
    Log.warning("disk is getting full")
    Log.error("tts stream error")
    recent = Log.recent(5)
    assert [r["level"] for r in recent[:2]] == ["error", "warning"]
    assert recent[0]["message"] == "tts stream error" and "test_log_facade" in recent[0]["where"]
    counts = Log.counts(60)
    assert counts["warning"] >= 1 and counts["error"] >= 1
    assert Log.recent(5, since=recent[0]["ts"]) == []
