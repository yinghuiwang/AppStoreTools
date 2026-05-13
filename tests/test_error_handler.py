"""Tests for error_handler module"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestIsDebug:
    """Tests for is_debug() function."""

    def test_debug_flag_set_via_underscore_asc_debug_1(self, monkeypatch):
        """_ASC_DEBUG=1 returns True."""
        monkeypatch.setenv("_ASC_DEBUG", "1")
        from asc.error_handler import is_debug
        assert is_debug() is True

    def test_debug_flag_set_via_underscore_asc_debug_0(self, monkeypatch):
        """_ASC_DEBUG=0 returns False."""
        monkeypatch.setenv("_ASC_DEBUG", "0")
        from asc.error_handler import is_debug
        assert is_debug() is False

    def test_debug_flag_set_via_asc_debug_1(self, monkeypatch):
        """ASC_DEBUG=1 (and _ASC_DEBUG not set) returns True."""
        monkeypatch.delenv("_ASC_DEBUG", raising=False)
        monkeypatch.setenv("ASC_DEBUG", "1")
        from asc.error_handler import is_debug
        assert is_debug() is True

    def test_debug_flag_set_via_asc_debug_0(self, monkeypatch):
        """ASC_DEBUG=0 (and _ASC_DEBUG not set) returns False."""
        monkeypatch.delenv("_ASC_DEBUG", raising=False)
        monkeypatch.setenv("ASC_DEBUG", "0")
        from asc.error_handler import is_debug
        assert is_debug() is False

    def test_no_debug_flag(self, monkeypatch):
        """Neither _ASC_DEBUG nor ASC_DEBUG set returns False."""
        monkeypatch.delenv("_ASC_DEBUG", raising=False)
        monkeypatch.delenv("ASC_DEBUG", raising=False)
        from asc.error_handler import is_debug
        assert is_debug() is False

    def test_underscore_asc_debug_takes_priority(self, monkeypatch):
        """_ASC_DEBUG takes priority over ASC_DEBUG."""
        monkeypatch.setenv("_ASC_DEBUG", "1")
        monkeypatch.setenv("ASC_DEBUG", "0")
        from asc.error_handler import is_debug
        assert is_debug() is True

    def test_debug_flag_true_string(self, monkeypatch):
        """_ASC_DEBUG=true returns True."""
        monkeypatch.setenv("_ASC_DEBUG", "true")
        from asc.error_handler import is_debug
        assert is_debug() is True

    def test_debug_flag_yes_string(self, monkeypatch):
        """_ASC_DEBUG=yes returns True."""
        monkeypatch.setenv("_ASC_DEBUG", "yes")
        from asc.error_handler import is_debug
        assert is_debug() is True


class TestGetErrorLogPath:
    """Tests for get_error_log_path() function."""

    def test_returns_error_log_path(self):
        """Returns Path('.asc/error.log')."""
        from asc.error_handler import get_error_log_path
        result = get_error_log_path()
        assert result == Path('.asc') / 'error.log'


class TestEnsureErrorLogDir:
    """Tests for ensure_error_log_dir() function."""

    def test_creates_directory_if_not_exists(self, tmp_path, monkeypatch):
        """Creates .asc/ directory if it doesn't exist."""
        monkeypatch.chdir(tmp_path)
        from asc.error_handler import ensure_error_log_dir
        ensure_error_log_dir()
        error_dir = tmp_path / '.asc'
        assert error_dir.exists()
        assert error_dir.is_dir()

    def test_does_not_raise_if_exists(self, tmp_path, monkeypatch):
        """Does not raise if .asc/ already exists."""
        monkeypatch.chdir(tmp_path)
        error_dir = tmp_path / '.asc'
        error_dir.mkdir()
        from asc.error_handler import ensure_error_log_dir
        # Should not raise
        ensure_error_log_dir()
        assert error_dir.exists()


class TestFormatTraceback:
    """Tests for format_traceback() function."""

    def test_returns_traceback_string(self):
        """Returns formatted traceback as string."""
        from asc.error_handler import format_traceback
        try:
            raise ValueError("test error")
        except ValueError as e:
            result = format_traceback(e)
        assert "ValueError" in result
        assert "test error" in result
        assert 'File "' in result


class TestGetUserMessage:
    """Tests for get_user_message() function."""

    def test_returns_message_for_known_exception(self, monkeypatch):
        """Returns translated message for known exception types."""
        monkeypatch.setattr("asc.i18n.LANG", "en")
        from asc.error_handler import get_user_message

        exc = FileNotFoundError("key.p8 not found")
        result = get_user_message(exc)
        assert "File not found" in result

    def test_extracts_error_code_from_message(self, monkeypatch):
        """Extracts error code from exception message."""
        monkeypatch.setattr("asc.i18n.LANG", "en")
        from asc.error_handler import get_user_message

        exc = Exception("API Error [401] Invalid token")
        result = get_user_message(exc)
        assert result == "Authentication failed. Please check your credentials (issuer_id, key_id, key_file)."

    def test_fallback_generic_message(self, monkeypatch):
        """Falls back to generic message for unknown exceptions."""
        monkeypatch.setattr("asc.i18n.LANG", "en")
        from asc.error_handler import get_user_message

        exc = RuntimeError("Something went wrong")
        result = get_user_message(exc)
        assert result == "Error: Something went wrong"

    def test_chinese_message(self, monkeypatch):
        """Returns Chinese message when LANG is zh."""
        monkeypatch.setattr("asc.i18n.LANG", "zh")
        from asc.error_handler import get_user_message

        exc = FileNotFoundError("key.p8 not found")
        result = get_user_message(exc)
        assert result == "文件未找到，请检查文件路径。"


class TestLogError:
    """Tests for log_error() function."""

    def test_log_error_creates_directory(self, tmp_path, monkeypatch):
        """Creates .asc/ directory if it doesn't exist."""
        monkeypatch.chdir(tmp_path)
        from asc.error_handler import log_error

        try:
            raise ValueError("test error")
        except ValueError as e:
            log_error("upload", "myapp", e)

        error_dir = tmp_path / '.asc'
        assert error_dir.exists()
        assert error_dir.is_dir()

    def test_log_error_creates_log_file(self, tmp_path, monkeypatch):
        """Creates error.log file with error entry."""
        monkeypatch.chdir(tmp_path)
        from asc.error_handler import log_error

        try:
            raise ValueError("test error")
        except ValueError as e:
            log_error("upload", "myapp", e)

        error_log = tmp_path / '.asc' / 'error.log'
        assert error_log.exists()
        content = error_log.read_text(encoding='utf-8')
        assert "ERROR" in content
        assert "upload" in content
        assert "myapp" in content
        assert "ValueError" in content
        assert "test error" in content

    def test_log_error_append(self, tmp_path, monkeypatch):
        """Appends to existing log file without overwriting."""
        monkeypatch.chdir(tmp_path)

        # Create .asc directory and initial log file
        error_dir = tmp_path / '.asc'
        error_dir.mkdir()
        error_log = error_dir / 'error.log'
        error_log.write_text("First error entry\n\n", encoding='utf-8')

        from asc.error_handler import log_error

        try:
            raise ValueError("second error")
        except ValueError as e:
            log_error("metadata", "myapp", e)

        content = error_log.read_text(encoding='utf-8')
        assert "First error entry" in content
        assert "second error" in content
        assert content.count("ValueError") == 2

    def test_log_error_with_timestamps(self, tmp_path, monkeypatch):
        """Log entries contain timestamp."""
        monkeypatch.chdir(tmp_path)
        from asc.error_handler import log_error

        try:
            raise ValueError("timestamp test")
        except ValueError as e:
            log_error("upload", "myapp", e)

        error_log = tmp_path / '.asc' / 'error.log'
        content = error_log.read_text(encoding='utf-8')
        # Timestamp format: YYYY-MM-DD HH:MM:SS
        import re
        assert re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', content)
