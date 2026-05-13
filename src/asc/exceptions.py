"""Custom exception classes for asc CLI."""

from __future__ import annotations


class AscError(Exception):
    """Base exception for asc CLI errors."""
    pass


class MissingConfigError(AscError):
    """Raised when required configuration is missing."""
    def __init__(self, missing: list[str], suggestion: str = ""):
        self.missing = missing
        self.suggestion = suggestion
        super().__init__(f"Missing required config: {', '.join(missing)}")


class MissingFileError(AscError):
    """Raised when a required file is not found."""
    def __init__(self, file_path: str, suggestion: str = ""):
        self.file_path = file_path
        self.suggestion = suggestion
        super().__init__(f"File not found: {file_path}")


class InvalidInputError(AscError):
    """Raised when user input is invalid."""
    def __init__(self, message: str, valid_options: list[str] = None):
        self.valid_options = valid_options or []
        super().__init__(message)


class GuardViolationError(AscError):
    """Raised when guard security check fails."""
    pass