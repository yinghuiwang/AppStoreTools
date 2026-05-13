"""Entry point for python -m asc"""

import sys
import warnings

# Suppress SSL warnings from urllib3 (not relevant to end users)
# Must be set before importing modules that use urllib3
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*ssl.*LibreSSL.*")

from asc.cli import app

if __name__ == "__main__":
    # Use standalone_mode=False to get exceptions instead of Typer's internal handling
    # This allows our exception handler to catch and log ALL errors
    app(standalone_mode=False)
