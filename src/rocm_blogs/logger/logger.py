"""
Centralized logging module for the ROCm Blogs package.

This module provides a unified logging interface to eliminate code duplication
and resolve circular dependency issues.
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

def log_message(
    level: str,
    message: str,
    operation: str = "general",
    component: str = "rocmblogs",
    **kwargs: Any,
) -> None:
    """Log message with level, operation, and component."""
    try:
        current_module = sys.modules.get("rocm_blogs") or sys.modules.get(
            "src.rocm_blogs"
        )
        if (
            hasattr(current_module, "structured_logger")
            and current_module.structured_logger
        ):
            structured_logger = current_module.structured_logger

            level_map = {
                "debug": "debug",
                "info": "info",
                "warning": "warning",
                "error": "error",
                "critical": "error",
            }

            log_method = getattr(
                structured_logger, level_map.get(level.lower(), "info"), None
            )
            if log_method:
                log_method(message, operation, component, **kwargs)
                return

        if is_logging_enabled_from_config():
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            rocm_blogs_log = logs_dir / "rocm_blogs.log"

            from datetime import datetime

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted_message = (
                f"[{timestamp}] [{level.upper()}] [{component}:{operation}] {message}\n"
            )

            with open(rocm_blogs_log, "a", encoding="utf-8") as f:
                f.write(formatted_message)

    except Exception:
        if level.lower() in ["error", "critical"]:
            try:
                from ..project.project_info import log_simple_message

                log_simple_message(
                    level, f"[{component}:{operation}] {message}", operation
                )
            except Exception:
                formatted_message = (
                    f"[{level.upper()}] [{component}:{operation}] {message}"
                )
                print(formatted_message, file=sys.stderr)


def create_step_log_file(step_name: str) -> tuple[Optional[str], Optional[Any]]:
    """Create log file for processing step only if logging is enabled."""
    try:
        if not is_logging_enabled_from_config():
            return None, None

        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{step_name}_{timestamp}.log"
        log_filepath = logs_dir / log_filename

        log_file_handle = open(log_filepath, "w", encoding="utf-8")

        return str(log_filepath), log_file_handle
    except Exception:
        return None, None


def safe_log_write(file_handle: Optional[Any], message: str) -> None:
    """Safely write message to log file."""
    if file_handle:
        try:
            file_handle.write(message)
            file_handle.flush()
        except (OSError, IOError):
            pass


def safe_log_message(
    level, message, operation="general", component="rocm_blogs", **kwargs
):
    """Safely log a message with fallback to stdout if logging fails."""
    try:
        log_message(level, message, operation, component, **kwargs)
    except Exception as log_error:
        print(f"[{level.upper()}] {message}")
        if level.upper() in ["ERROR", "CRITICAL"]:
            print(f"[WARNING] Logging system error: {log_error}")


def safe_log_close(file_handle: Optional[Any]) -> None:
    """Safely close log file handle."""
    if file_handle:
        try:
            file_handle.close()
        except (OSError, IOError):
            pass


def is_logging_enabled_from_config() -> bool:
    """Check if logging is enabled in configuration."""
    try:
        current_module = sys.modules.get("rocm_blogs") or sys.modules.get(
            "src.rocm_blogs"
        )
        if (
            hasattr(current_module, "structured_logger")
            and current_module.structured_logger
        ):
            return True

        return os.environ.get("ROCM_BLOGS_DEBUG", "").lower() in ("true", "1", "yes")
    except Exception:
        return False
