"""Unified error handling module for asc CLI."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from asc.i18n import LANG, t

# Flag to track if an error was already logged by the exception handler
_error_logged = False

# Error message translations
ERROR_MESSAGES: dict[str, dict[str, str]] = {
    # HTTP Error Codes
    '401': {
        'en': 'Authentication failed. Please check your credentials (issuer_id, key_id, key_file).',
        'zh': '认证失败，请检查凭证信息（issuer_id, key_id, key_file）。',
    },
    '403': {
        'en': 'Access forbidden. Your credentials do not have permission for this operation.',
        'zh': '访问被拒绝，您的凭证没有执行此操作的权限。',
    },
    '404': {
        'en': 'Resource not found. The requested resource may have been deleted or does not exist.',
        'zh': '资源未找到，请求的资源可能被删除或不存在。',
    },
    '429': {
        'en': 'Rate limit exceeded. Please wait a moment and try again.',
        'zh': '请求过于频繁，请稍后重试。',
    },
    '500': {
        'en': 'Internal server error. Please try again later.',
        'zh': '服务器内部错误，请稍后重试。',
    },
    '502': {
        'en': 'Bad gateway. Please try again later.',
        'zh': '网关错误，请稍后重试。',
    },
    '503': {
        'en': 'Service unavailable. Please try again later.',
        'zh': '服务不可用，请稍后重试。',
    },
    # Exception Types
    'AppStoreConnectError': {
        'en': 'App Store Connect API error.',
        'zh': 'App Store Connect API 错误。',
    },
    'AuthenticationError': {
        'en': 'Authentication failed. Please check your credentials.',
        'zh': '认证失败，请检查凭证信息。',
    },
    'NetworkError': {
        'en': 'Network error. Please check your internet connection.',
        'zh': '网络错误，请检查网络连接。',
    },
    'ValidationError': {
        'en': 'Validation error. Please check your input data.',
        'zh': '验证错误，请检查输入数据。',
    },
    'FileNotFoundError': {
        'en': 'File not found. Please check the file path.',
        'zh': '文件未找到，请检查文件路径。',
    },
    'TimeoutError': {
        'en': 'Request timeout. Please try again.',
        'zh': '请求超时，请稍后重试。',
    },
}


def is_debug() -> bool:
    """Check if debug mode is enabled.

    Priority: _ASC_DEBUG env var (from --debug CLI flag) > ASC_DEBUG env var > False
    """
    if os.environ.get('_ASC_DEBUG', '').strip().lower() in ('1', 'true', 'yes'):
        return True
    if os.environ.get('ASC_DEBUG', '').strip().lower() in ('1', 'true', 'yes'):
        return True
    return False


def get_error_log_path() -> Path:
    """Return the error log path: .asc/error.log (relative to CWD)."""
    return Path('.asc') / 'error.log'


def ensure_error_log_dir() -> None:
    """Ensure .asc/ directory exists, create if not."""
    error_dir = Path('.asc')
    if not error_dir.exists():
        error_dir.mkdir(parents=True, exist_ok=True)


def format_traceback(exc: BaseException) -> str:
    """Format exception with full traceback as string."""
    return ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _extract_error_code(exc: BaseException) -> Optional[str]:
    """Extract HTTP error code (401/403/404/429/500/502/503) from exception message."""
    exc_str = str(exc)
    for code in ('401', '403', '404', '429', '500', '502', '503'):
        if code in exc_str:
            return code
    return None


def get_user_message(exc: BaseException) -> str:
    """Get user-friendly error message based on exception type and error code.

    First checks ERROR_MESSAGES by exception class name, then extracts error code
    from exception message.
    """
    # Try exception class name first
    exc_name = type(exc).__name__
    if exc_name in ERROR_MESSAGES:
        return t(ERROR_MESSAGES[exc_name])

    # Try error code extraction from message
    error_code = _extract_error_code(exc)
    if error_code and error_code in ERROR_MESSAGES:
        return t(ERROR_MESSAGES[error_code])

    # Fallback to generic message
    generic_messages = {
        'en': f'Error: {exc}',
        'zh': f'错误：{exc}',
    }
    return generic_messages.get(LANG, generic_messages['en'])


def log_error(command: str, app_name: str, exc: BaseException) -> None:
    """Append error to .asc/error.log with formatted traceback.

    Format:
    2026-05-12 15:30:45 | ERROR | upload | myapp | API 错误 [401] GET /v1/apps/xxx: Invalid token
    Traceback (most recent call last):
      File "...", line 123, in upload
        ...
    """
    ensure_error_log_dir()
    error_log_path = get_error_log_path()

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_msg = get_user_message(exc)

    # Build the log entry
    log_entry_lines = [
        f'{timestamp} | ERROR | {command} | {app_name} | {user_msg}',
        format_traceback(exc),
        '',  # Empty line separator
    ]
    log_entry = '\n'.join(log_entry_lines)

    with open(error_log_path, 'a', encoding='utf-8') as f:
        f.write(log_entry)


def _print_colored_traceback(exc: BaseException) -> None:
    """Print colored traceback to stderr in debug mode."""
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    red = typer.style
    for line in tb_lines:
        # Color the traceback lines
        if line.startswith('  File'):
            # File/line info in yellow
            sys.stderr.write(red(line, fg=typer.colors.YELLOW))
        elif line.startswith('    '):
            # Code context in white
            sys.stderr.write(red(line, fg=typer.colors.WHITE))
        else:
            # Other lines (traceback header, etc.) in red
            sys.stderr.write(red(line, fg=typer.colors.RED))
        sys.stderr.write('\n' if not line.endswith('\n') else '')


def handle_error(command: str, app_name: str, exc: BaseException) -> None:
    """Main error handling entry point.

    - Debug mode: print colored full traceback to stderr
    - Non-debug: write to error.log, display user-friendly message to stderr
    """
    if is_debug():
        # Debug mode: print colored traceback
        sys.stderr.write(typer.style('Traceback (most recent call last):\n',
                                     fg=typer.colors.RED, bold=True))
        _print_colored_traceback(exc)
    else:
        # Non-debug: log to file and show user-friendly message
        log_error(command, app_name, exc)
        user_msg = get_user_message(exc)
        sys.stderr.write(typer.style(f'Error: {user_msg}\n', fg=typer.colors.RED))
        sys.stderr.write(typer.style(
            'Error details have been logged to .asc/error.log\n',
            fg=typer.colors.YELLOW
        ))


def _global_exception_handler(exc_type, exc_value, exc_traceback):
    """Global exception handler registered via sys.excepthook."""
    global _error_logged
    if issubclass(exc_type, KeyboardInterrupt):
        # Allow KeyboardInterrupt to be handled normally
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Format and display the error
    exc = exc_value
    handle_error('unknown', 'unknown', exc)
    _error_logged = True


def install() -> None:
    """Register global exception handler to sys.excepthook."""
    global _error_logged
    _error_logged = False
    sys.excepthook = _global_exception_handler
