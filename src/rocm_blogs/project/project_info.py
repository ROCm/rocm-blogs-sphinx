"""
Project information and universal logging for ROCm Blogs.

This module provides standalone logging functionality that works independently
of any external logging packages like rocm_blogs_logging. It creates universal
log files on every run with project information and execution tracking.
"""

import os
import sys
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path

try:
    import sphinx
except Exception:
    sphinx = None

from .._version import __version__ as PROJECT_VERSION
from ..logger.logger import log_message

# Project Information
PROJECT_NAME = "ROCm Blogs Sphinx Extension"
PROJECT_EMAIL = "Danny.Guan@amd.com"
PROJECT_DESCRIPTION = "Sphinx extension for generating ROCm blog documentation"

# Global variable to store the current log file path
_current_log_file = None


def safe_write_log(file_path: str, message: str):
    """Safely write to log file with error handling."""
    if not file_path:
        return

    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(message)
            f.flush()  # Ensure immediate write
    except (OSError, IOError) as e:
        # Fallback to console if file write fails
        print(f"[LOG WRITE ERROR] {e}: {message.strip()}", file=sys.stderr)


def create_universal_log():
    """Create a universal log file that gets created on every run."""
    global _current_log_file

    try:
        sphinx_version = (
            getattr(sphinx, "__version__", "unknown") if sphinx else "unknown"
        )

        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = logs_dir / f"rocm_blogs_universal_{timestamp}.log"

        header_content = f"""{'=' * 80}
ROCm BLOGS UNIVERSAL LOG
{'=' * 80}
Timestamp: {datetime.now().isoformat()}
Project: {PROJECT_NAME}
Version: {PROJECT_VERSION}
Email: {PROJECT_EMAIL}
Description: {PROJECT_DESCRIPTION}
{'=' * 80}

SYSTEM INFORMATION:
{'-' * 40}
Working Directory: {os.getcwd()}
Python Version: {sys.version.split()[0]}
Python Executable: {sys.executable}
Platform: {sys.platform}
Sphinx Version: {sphinx_version}
Python Path: {os.environ.get('PYTHONPATH', 'Not set')}
Environment: {os.environ.get('ENV', 'Not specified')}

BUILD EXECUTION LOG:
{'-' * 40}
Build started at: {datetime.now().isoformat()}

"""

        with open(log_file, "w", encoding="utf-8") as f:
            f.write(header_content)

        _current_log_file = str(log_file)
        log_message(
            "info",
            f"Created universal log file at {log_file}",
            "project_info",
            "logging",
        )
        return str(log_file)

    except Exception as e:
        log_message(
            "warning",
            f"Could not create universal log file: {e}",
            "project_info",
            "logging",
        )
        print(f"[WARNING] Could not create universal log file: {e}", file=sys.stderr)
        print(f"{PROJECT_NAME} v{PROJECT_VERSION}")
        _current_log_file = None
        return None


def log_project_info(func):
    """Decorator that creates a universal log file and logs project info on every run."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        log_file_path = create_universal_log()

        # Print to console - this works regardless of logging package availability
        print(f"\n{PROJECT_NAME} v{PROJECT_VERSION}")
        if log_file_path:
            print(f"Universal log: {log_file_path}")
        print("-" * 50)
        log_message(
            "info",
            f"Starting build for {PROJECT_NAME} v{PROJECT_VERSION}",
            "project_info",
            "build",
        )

        start_time = time.time()

        try:
            # Execute the function
            result = func(*args, **kwargs)

            # Calculate duration
            duration = time.time() - start_time

            # Log completion
            completion_msg = (
                f"Setup completed successfully at: {datetime.now().isoformat()}\n"
            )
            completion_msg += f"Total duration: {duration:.2f} seconds\n"
            completion_msg += "=" * 80 + "\n"

            safe_write_log(log_file_path, completion_msg)
            log_message(
                "info",
                f"Build completed successfully in {duration:.2f}s",
                "project_info",
                "build",
            )

            return result

        except Exception as e:
            duration = time.time() - start_time

            error_msg = f"Setup failed at: {datetime.now().isoformat()}\n"
            error_msg += f"Duration before failure: {duration:.2f} seconds\n"
            error_msg += f"Error: {str(e)}\n"
            error_msg += f"Traceback:\n{traceback.format_exc()}\n"
            error_msg += "=" * 80 + "\n"

            safe_write_log(log_file_path, error_msg)
            log_message(
                "error",
                f"Build failed after {duration:.2f}s: {e}",
                "project_info",
                "build",
            )

            print(f"\n[ERROR] Build failed: {e}", file=sys.stderr)

            raise

    return wrapper


def append_to_universal_log(message: str):
    """Append a message to the current universal log file."""
    global _current_log_file

    if _current_log_file and os.path.exists(_current_log_file):
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_write_log(_current_log_file, f"[{timestamp}] {message}\n")
        return

    try:
        logs_dir = Path("logs")
        if not logs_dir.exists():
            return

        universal_logs = list(logs_dir.glob("rocm_blogs_universal_*.log"))
        if not universal_logs:
            return

        # Get the most recent log file
        latest_log = max(universal_logs, key=lambda x: x.stat().st_mtime)

        # Append message with timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        safe_write_log(str(latest_log), f"[{timestamp}] {message}\n")

    except Exception:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def log_simple_message(level: str, message: str, category: str = "general"):
    """Simple logging function that works without external dependencies."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] [{level.upper()}] [{category}] {message}"

    append_to_universal_log(f"[{level.upper()}] [{category}] {message}")

    if level.lower() in ["error", "critical"]:
        print(formatted_msg, file=sys.stderr)
    else:
        print(formatted_msg)


def get_project_info():
    """Get project information as a dictionary."""
    return {
        "name": PROJECT_NAME,
        "version": PROJECT_VERSION,
        "email": PROJECT_EMAIL,
        "description": PROJECT_DESCRIPTION,
    }
