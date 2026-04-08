import csv
import os
from pathlib import Path
from typing import Iterable


class CsvJournalWriter:
    def __init__(self, filepath: str, fieldnames: list[str]):
        self.filepath = Path(filepath)
        self.fieldnames = fieldnames

        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        if not self.filepath.exists():
            self.reset()

    def _safe_open_append(self):
        # line-buffering para reducir riesgo de retención en buffers de usuario
        return self.filepath.open(
            "a",
            newline="",
            encoding="utf-8",
            buffering=1,
        )

    def _safe_open_write(self):
        return self.filepath.open(
            "w",
            newline="",
            encoding="utf-8",
            buffering=1,
        )

    def _flush_and_fsync(self, file) -> None:
        file.flush()
        os.fsync(file.fileno())

    def _sanitize_row(self, row: dict) -> dict:
        sanitized = {}
        for field in self.fieldnames:
            value = row.get(field, "")
            if value is None:
                value = ""
            sanitized[field] = value
        return sanitized

    def reset(self) -> None:
        with self._safe_open_write() as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            self._flush_and_fsync(file)

    def append_row(self, row: dict) -> None:
        sanitized_row = self._sanitize_row(row)

        with self._safe_open_append() as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writerow(sanitized_row)
            self._flush_and_fsync(file)

    def append_rows(self, rows: Iterable[dict]) -> None:
        with self._safe_open_append() as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)

            for row in rows:
                sanitized_row = self._sanitize_row(row)
                writer.writerow(sanitized_row)

            self._flush_and_fsync(file)