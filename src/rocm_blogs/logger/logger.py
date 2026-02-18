"""
Centralized logging module for the ROCm Blogs package.

This module provides a unified logging interface to eliminate code duplication
and resolve circular dependency issues.
"""

import os
import re
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


_SAFE_LOG_LEVEL_RE = re.compile(
    r"^\s*(CRITICAL|ERROR|TRACEBACK|WARNING|WARN|DEBUG)\b", re.IGNORECASE
)


def _infer_safe_log_level(message: str) -> str:
    match = _SAFE_LOG_LEVEL_RE.match(message or "")
    if not match:
        return "info"
    token = match.group(1).upper()
    if token == "CRITICAL":
        return "critical"
    if token in ("ERROR", "TRACEBACK"):
        return "error"
    if token in ("WARNING", "WARN"):
        return "warning"
    if token == "DEBUG":
        return "debug"
    return "info"


def _infer_safe_log_operation(file_handle: Optional[Any]) -> str:
    if not file_handle:
        return "step_log"
    name = getattr(file_handle, "name", "")
    if not name:
        return "step_log"
    try:
        stem = Path(str(name)).stem
    except Exception:
        return "step_log"
    parts = stem.split("_")
    if (
        len(parts) >= 3
        and parts[-2].isdigit()
        and parts[-1].isdigit()
        and len(parts[-2]) == 8
        and len(parts[-1]) == 6
    ):
        step = "_".join(parts[:-2])
        if step:
            return step
    return stem or "step_log"


def safe_log_write(file_handle: Optional[Any], message: str) -> None:
    """Safely write message to log file."""
    if file_handle:
        try:
            file_handle.write(message)
            file_handle.flush()
        except (OSError, IOError):
            pass

    try:
        current_module = sys.modules.get("rocm_blogs") or sys.modules.get(
            "src.rocm_blogs"
        )
        structured_logger = getattr(current_module, "structured_logger", None)
        if not structured_logger:
            return

        operation = _infer_safe_log_operation(file_handle)
        component = "step_log"
        level = _infer_safe_log_level(message)

        log_path = getattr(file_handle, "name", None) if file_handle else None
        extra_data = {"log_source": "safe_log_write"}
        if log_path:
            extra_data["log_path"] = str(log_path)

        lines = message.splitlines()
        if not lines:
            lines = [message]

        for line in lines:
            if line == "":
                continue
            log_message(level, line, operation, component, extra_data=extra_data)
    except Exception:
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
