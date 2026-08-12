import codecs
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL = 0.08
TAIL_LINES_ON_FAILURE = 20
READ_CHUNK_SIZE = 8192


class ProcessCanceled(RuntimeError):
    """Raised when a subprocess is canceled by the caller."""


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
        followed by last 20 lines of log file on stderr
      - Returns subprocess.CompletedProcess (returncode + empty stdout/stderr — caller uses log file)

    Behavior in non-TTY mode (verbose=False, isatty()==False):
      - No spinner; emit "▶ {label}..." once at start
      - Same log file tee
      - Same final ✅/❌ + elapsed line, plus tail-on-fail (stderr)

    Behavior in verbose mode (verbose=True):
      - No spinner. Subprocess stdout/stderr pass through to caller's terminal directly.
      - Still tee to log file as a backup.
      - Final ✅/❌ + elapsed line.

    When on_log_line is set (e.g. Web TaskReporter):
      - Every non-empty output line is forwarded during the tee loop (live streaming).
      - Final ✅/❌ summary (and log path on failure) is also forwarded.
      - Failure tail is not re-forwarded (already streamed).

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
        on_log_line: Optional[Callable[[str], None]] = None,
    ):
        self.label = label
        self.log_path = Path(log_path)
        self.verbose = verbose
        self.on_log_line = on_log_line
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

    def _emit_log_line(self, message: str) -> None:
        if self.on_log_line is None:
            return
        text = str(message).rstrip("\n\r")
        if text:
            self.on_log_line(text)

    def _safe_emit_log_line(self, message: str) -> None:
        try:
            self._emit_log_line(message)
        except Exception:
            logging.getLogger("asc.web").exception(
                "raw log callback failed after tee path=%s",
                self.log_path,
            )

    def _safe_emit_application(self, message: str, *, level: str = "info") -> None:
        application = getattr(self.on_log_line, "application", None)
        try:
            if callable(application):
                application(message, level=level)
            else:
                self._emit_log_line(message)
        except Exception:
            logging.getLogger("asc.web").exception(
                "application log callback failed path=%s",
                self.log_path,
            )

    def _safe_output_line(
        self,
        output_callback: Optional[Callable[[str], None]],
        line: str,
    ) -> None:
        if output_callback is None:
            return
        try:
            output_callback(line)
        except Exception:
            logging.getLogger("asc.web").exception(
                "subprocess output callback failed after tee path=%s",
                self.log_path,
            )

    def _finish_callback(self, *, failed: bool) -> None:
        finish_callback = getattr(self.on_log_line, "finish", None)
        flush_callback = getattr(self.on_log_line, "flush", None)
        try:
            if callable(finish_callback):
                finish_callback(failed=failed)
            elif callable(flush_callback):
                flush_callback()
        except Exception:
            logging.getLogger("asc.web").exception(
                "raw log callback finalization failed path=%s",
                self.log_path,
            )

    @staticmethod
    def _terminate_process(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (AttributeError, OSError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (AttributeError, OSError):
                proc.kill()

    @staticmethod
    def _write_all(log_file, chunk: bytes) -> None:
        """Write one raw subprocess chunk completely or fail explicitly."""
        view = memoryview(chunk)
        offset = 0
        while offset < len(view):
            written = log_file.write(view[offset:])
            if written is None or written <= 0:
                raise OSError("raw log write made no progress")
            if written > len(view) - offset:
                raise OSError("raw log write returned an invalid byte count")
            offset += written

    def _print_tail(self) -> None:
        """Echo last N log lines to stderr for CLI operators.

        Does not call on_log_line — lines were already streamed during tee.
        """
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

    def run(
        self,
        cmd: list,
        output_callback: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> subprocess.CompletedProcess:
        start = time.monotonic()
        proc = None
        log_file = None
        spinner_thread = None
        cancel_thread = None
        returncode = None
        original_error = None
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(self.log_path, "wb", buffering=0)

            if not self.tty and not self.verbose:
                sys.stderr.write(f"▶ {self.label}...\n")
                sys.stderr.flush()

            if self.tty and not self.verbose:
                spinner_thread = threading.Thread(
                    target=self._spinner_loop, args=(start,), daemon=True
                )
                spinner_thread.start()

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                text=False,
                start_new_session=True,
            )

            def _watch_cancel() -> None:
                if cancel_event is None or proc is None:
                    return
                while proc.poll() is None and not cancel_event.wait(timeout=0.1):
                    pass
                if cancel_event.is_set():
                    self._terminate_process(proc)

            if cancel_event is not None:
                cancel_thread = threading.Thread(target=_watch_cancel, daemon=True)
                cancel_thread.start()
            assert proc.stdout is not None

            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            pending_text = ""

            def _emit_text(text: str, *, final: bool = False) -> None:
                nonlocal pending_text
                pending_text += text
                while "\n" in pending_text:
                    line, pending_text = pending_text.split("\n", 1)
                    rendered = line + "\n"
                    self._safe_output_line(output_callback, rendered)
                    self._safe_emit_log_line(rendered)
                    if self.verbose:
                        sys.stdout.write(rendered)
                        sys.stdout.flush()
                if final and pending_text:
                    rendered = pending_text
                    pending_text = ""
                    self._safe_output_line(output_callback, rendered)
                    self._safe_emit_log_line(rendered)
                    if self.verbose:
                        sys.stdout.write(rendered)
                        sys.stdout.flush()

            while True:
                chunk = proc.stdout.read(READ_CHUNK_SIZE)
                if not chunk:
                    break
                self._write_all(log_file, chunk)
                _emit_text(decoder.decode(chunk))
            _emit_text(decoder.decode(b"", final=True), final=True)
            returncode = proc.wait()

            elapsed = format_elapsed(time.monotonic() - start)
            canceled = cancel_event is not None and cancel_event.is_set()
            if canceled:
                canceled_msg = f"⏹ {self.label} 已终止 ({elapsed})"
                sys.stderr.write(canceled_msg + "\n")
                sys.stderr.flush()
                self._safe_emit_application(canceled_msg)
                raise ProcessCanceled(f"{self.label} canceled")
            if returncode == 0:
                ok_msg = f"✅ {self.label} 完成 ({elapsed})"
                sys.stderr.write(ok_msg + "\n")
                self._safe_emit_application(ok_msg)
            else:
                fail_msg = f"❌ {self.label} 失败 ({elapsed})"
                log_hint = f"   完整日志: {self.log_path}"
                sys.stderr.write(fail_msg + "\n")
                sys.stderr.write(log_hint + "\n")
                self._safe_emit_application(fail_msg, level="error")
                self._safe_emit_application(log_hint)
                self._print_tail()
            sys.stderr.flush()

            return subprocess.CompletedProcess(
                args=cmd, returncode=returncode, stdout="", stderr=""
            )
        except BaseException as exc:
            original_error = exc
            if proc is not None:
                try:
                    self._terminate_process(proc)
                except Exception:
                    logging.getLogger("asc.web").exception(
                        "subprocess cleanup failed path=%s",
                        self.log_path,
                    )
            raise
        finally:
            cleanup_error = None
            self._stop.set()
            for cleanup in (
                (
                    lambda: spinner_thread.join(timeout=1.0)
                    if spinner_thread is not None
                    else None
                ),
                (
                    lambda: cancel_thread.join(timeout=0.2)
                    if cancel_thread is not None
                    else None
                ),
                self._clear_line,
                lambda: log_file.close() if log_file is not None else None,
            ):
                try:
                    cleanup()
                except Exception as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
                    logging.getLogger("asc.web").exception(
                        "Spinner cleanup failed path=%s",
                        self.log_path,
                    )
            canceled = cancel_event is not None and cancel_event.is_set()
            self._finish_callback(
                failed=canceled or returncode is None or returncode != 0
            )
            if cleanup_error is not None and original_error is None:
                raise cleanup_error
