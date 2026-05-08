import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL = 0.08
TAIL_LINES_ON_FAILURE = 20


def format_elapsed(seconds: float) -> str:
    """Return 'MM:SS' or 'HH:MM:SS' style string."""
    s = int(seconds)
    if s < 3600:
        return f"{s // 60:02d}:{s % 60:02d}"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


class Spinner:
    """Subprocess runner with spinner UI and log file tee.

    Behavior in TTY mode:
      - Background thread refreshes a spinner glyph + elapsed time on stderr (carriage return)
      - Subprocess stdout+stderr combined and tee'd to log_path (line-flushed)
      - On success: clear spinner line, print "✅ {label} 完成 ({elapsed})"
      - On failure: clear spinner line, print "❌ {label} 失败 ({elapsed})\\n   完整日志: {log_path}",
        followed by last 20 lines of log file
      - Returns subprocess.CompletedProcess (returncode + empty stdout/stderr — caller uses log file)

    Behavior in non-TTY mode (verbose=False, isatty()==False):
      - No spinner; emit "▶ {label}..." once at start
      - Same log file tee
      - Same final ✅/❌ + elapsed line, plus tail-on-fail

    Behavior in verbose mode (verbose=True):
      - No spinner. Subprocess stdout/stderr pass through to caller's terminal directly.
      - Still tee to log file as a backup.
      - Final ✅/❌ + elapsed line.

    Usage:
        sp = Spinner("构建 Archive", log_path="build/build.log", verbose=False)
        result = sp.run(["xcodebuild", "archive", "-scheme", "X"])
        if result.returncode != 0:
            raise RuntimeError(...)
    """

    def __init__(
        self,
        label: str,
        *,
        log_path,
        verbose: bool = False,
        tty: Optional[bool] = None,
    ):
        self.label = label
        self.log_path = Path(log_path)
        self.verbose = verbose
        if tty is None:
            tty = sys.stderr.isatty()
        self.tty = tty
        self._stop = threading.Event()

    def _spinner_loop(self, start_time: float) -> None:
        i = 0
        try:
            while not self._stop.is_set():
                frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
                elapsed = format_elapsed(time.monotonic() - start_time)
                sys.stderr.write(f"\r{frame} {self.label} {elapsed}")
                sys.stderr.flush()
                i += 1
                self._stop.wait(SPINNER_INTERVAL)
        except Exception:
            pass

    def _clear_line(self) -> None:
        if self.tty and not self.verbose:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

    def _print_tail(self) -> None:
        try:
            lines = self.log_path.read_text(errors="replace").splitlines()
        except Exception:
            return
        tail = lines[-TAIL_LINES_ON_FAILURE:]
        if tail:
            sys.stderr.write("   ── 最后 " + str(len(tail)) + " 行 ──\n")
            for line in tail:
                sys.stderr.write(f"   {line}\n")
            sys.stderr.flush()

    def run(self, cmd: list) -> subprocess.CompletedProcess:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(self.log_path, "w", buffering=1)  # line-buffered

        if not self.tty and not self.verbose:
            sys.stderr.write(f"▶ {self.label}...\n")
            sys.stderr.flush()

        start = time.monotonic()
        spinner_thread = None
        if self.tty and not self.verbose:
            spinner_thread = threading.Thread(
                target=self._spinner_loop, args=(start,), daemon=True
            )
            spinner_thread.start()

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                log_file.write(line)
                if self.verbose:
                    sys.stdout.write(line)
                    sys.stdout.flush()
            returncode = proc.wait()
        finally:
            self._stop.set()
            if spinner_thread is not None:
                spinner_thread.join(timeout=1.0)
            self._clear_line()
            log_file.close()

        elapsed = format_elapsed(time.monotonic() - start)
        if returncode == 0:
            sys.stderr.write(f"✅ {self.label} 完成 ({elapsed})\n")
        else:
            sys.stderr.write(f"❌ {self.label} 失败 ({elapsed})\n")
            sys.stderr.write(f"   完整日志: {self.log_path}\n")
            self._print_tail()
        sys.stderr.flush()

        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout="", stderr=""
        )
