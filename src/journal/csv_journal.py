import csv
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

    def reset(self) -> None:
        with self.filepath.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()

    def append_row(self, row: dict) -> None:
        with self.filepath.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writerow(row)

    def append_rows(self, rows: Iterable[dict]) -> None:
        with self.filepath.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            for row in rows:
                writer.writerow(row)