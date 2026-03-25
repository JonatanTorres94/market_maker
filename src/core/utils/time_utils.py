#src/core/utils/time_utils.py
from datetime import UTC, datetime
from typing import Optional

def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def exchange_ms_to_iso(value: Optional[int]) -> str:
    if value is None:
        return utc_now_iso()
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()