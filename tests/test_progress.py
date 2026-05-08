import os
import subprocess
import sys
from pathlib import Path

import pytest

from asc.progress import Spinner, format_elapsed


def test_format_elapsed_short():
    assert format_elapsed(0) == "00:00"
    assert format_elapsed(5) == "00:05"
    assert format_elapsed(65) == "01:05"
    assert format_elapsed(3599) == "59:59"


def test_format_elapsed_long():
    assert format_elapsed(3600) == "01:00:00"
    assert format_elapsed(3725) == "01:02:05"
    assert format_elapsed(36000) == "10:00:00"


def test_spinner_runs_command_and_writes_log(tmp_path):
    log = tmp_path / "out.log"
    sp = Spinner("Echo test", log_path=str(log), verbose=False, tty=False)
    result = sp.run([sys.executable, "-c", "print('hello world')"])
    assert result.returncode == 0
    assert "hello world" in log.read_text()


def test_spinner_failure_returns_nonzero(tmp_path, capsys):
    log = tmp_path / "out.log"
    sp = Spinner("Fail test", log_path=str(log), verbose=False, tty=False)
    result = sp.run([sys.executable, "-c", "import sys; print('oops'); sys.exit(2)"])
    assert result.returncode == 2
    assert "oops" in log.read_text()
    err = capsys.readouterr().err
    assert "❌" in err
    assert "Fail test" in err
    assert "oops" in err  # tail of log echoed on failure


def test_spinner_tty_mode_shows_label(tmp_path, capsys):
    log = tmp_path / "out.log"
    sp = Spinner("Spinning", log_path=str(log), verbose=False, tty=True)
    result = sp.run([sys.executable, "-c", "print('x')"])
    assert result.returncode == 0
    err = capsys.readouterr().err
    assert "Spinning" in err
    assert "✅" in err


def test_spinner_verbose_mode_passes_output_through(tmp_path, capsys):
    """verbose=True: stdout/stderr should appear in the captured output (passthrough),
    AND the log file should still contain the output."""
    log = tmp_path / "out.log"
    sp = Spinner("Verbose test", log_path=str(log), verbose=True, tty=False)
    result = sp.run([sys.executable, "-c", "print('VISIBLE_LINE')"])
    assert result.returncode == 0
    captured = capsys.readouterr()
    # Either stdout or stderr should contain it (we pass through)
    assert "VISIBLE_LINE" in (captured.out + captured.err)
    assert "VISIBLE_LINE" in log.read_text()


def test_spinner_creates_parent_dir(tmp_path):
    log = tmp_path / "deep" / "nested" / "out.log"
    sp = Spinner("Mkdir test", log_path=str(log), verbose=False, tty=False)
    result = sp.run([sys.executable, "-c", "print('ok')"])
    assert result.returncode == 0
    assert log.is_file()


def test_spinner_tail_limit_on_failure(tmp_path, capsys):
    """Failure tail should not echo more than ~20 lines."""
    log = tmp_path / "out.log"
    sp = Spinner("Tail test", log_path=str(log), verbose=False, tty=False)
    # Generate 50 lines
    code = "import sys\n" + "\n".join(f"print('line{i}')" for i in range(50)) + "\nsys.exit(1)\n"
    result = sp.run([sys.executable, "-c", code])
    assert result.returncode == 1
    err = capsys.readouterr().err
    # First lines (line0-line29) should NOT appear in tail; last lines should
    assert "line49" in err
    assert "line0\n" not in err  # exact match — line0 should be tail-trimmed
