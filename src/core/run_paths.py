# src/core/run_paths.py
from datetime import UTC, datetime


def build_default_session_id(prefix: str = "paper") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{timestamp}"
