"""Entry point for python -m asc"""

import sys
import warnings

# Suppress SSL warnings from urllib3 (not relevant to end users)
# Must be set before importing modules that use urllib3
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")
warnings.filterwarnings("ignore", message=".*ssl.*LibreSSL.*")

from asc.cli import run_app

if __name__ == "__main__":
    sys.exit(run_app())
