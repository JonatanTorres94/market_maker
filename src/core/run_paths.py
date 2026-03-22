# src/core/run_paths.py
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_JOURNAL_BASE_PATH = "data/journals"
DEFAULT_REPORTS_BASE_PATH = "data/reports"


def get_run_session_id() -> str | None:
    raw = os.getenv("RUN_SESSION_ID", "").strip()
    return raw or None


def get_run_root() -> Path | None:
    session_id = get_run_session_id()
    if not session_id:
        return None
    return Path("data/runs") / session_id


def get_journal_base_path() -> str:
    explicit = os.getenv("JOURNAL_BASE_PATH", "").strip()
    if explicit:
        return explicit

    run_root = get_run_root()
    if run_root is not None:
        return str(run_root / "journals")

    return DEFAULT_JOURNAL_BASE_PATH


def get_reports_base_path() -> str:
    explicit = os.getenv("REPORTS_BASE_PATH", "").strip()
    if explicit:
        return explicit

    run_root = get_run_root()
    if run_root is not None:
        return str(run_root / "reports")

    return DEFAULT_REPORTS_BASE_PATH


def ensure_run_directories() -> None:
    Path(get_journal_base_path()).mkdir(parents=True, exist_ok=True)
    Path(get_reports_base_path()).mkdir(parents=True, exist_ok=True)

    run_root = get_run_root()
    if run_root is not None:
        run_root.mkdir(parents=True, exist_ok=True)


def write_run_meta(payload: dict[str, Any]) -> Path | None:
    run_root = get_run_root()
    if run_root is None:
        return None

    run_root.mkdir(parents=True, exist_ok=True)
    path = run_root / "meta.json"

    enriched = {
        "run_session_id": get_run_session_id(),
        "generated_at": datetime.now(UTC).isoformat(),
        **payload,
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=4)

    return path


def build_default_session_id(prefix: str = "paper") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{timestamp}"