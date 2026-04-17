from __future__ import annotations

import threading
from datetime import UTC, datetime

from src.db.database import Database


class SectionMarkerService:
    """
    Daemon thread that writes time-period markers into the DB on a fixed interval.
    Each period is opened immediately and closed when the next one starts (or on stop).
    """

    def __init__(self, db: Database, session_id: str, interval_seconds: int = 3600):
        self._db = db
        self._session_id = session_id
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="section-marker"
        )
        self._current_marker_id: int | None = None
        self._period_num = 0

    def start(self) -> None:
        self._open_period()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._current_marker_id is not None:
            self._db.close_section_marker(
                self._current_marker_id, datetime.now(UTC).isoformat()
            )

    def _open_period(self) -> None:
        self._period_num += 1
        now = datetime.now(UTC).isoformat()
        self._current_marker_id = self._db.insert_section_marker(
            session_id=self._session_id,
            label=f"period_{self._period_num}",
            marker_type="hourly",
            started_at=now,
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if self._current_marker_id is not None:
                self._db.close_section_marker(
                    self._current_marker_id, datetime.now(UTC).isoformat()
                )
            self._open_period()
