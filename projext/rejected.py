"""
rejected_records sink.

Currently writes to CSV (one file per run). Swap this class's `flush`/`write`
internals for a real DB insert once Person 3's Postgres schema exists —
the interface (`write(...)`) is what the rest of the pipeline depends on,
so that swap shouldn't ripple outward.
"""

import csv
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class RejectedRecord:
    source: str            # "source_a" / "source_b"
    resource_type: str     # "patients", "encounters", etc.
    row_number: int         # 1-indexed row number in the original file (for tracing back)
    reason: str             # human-readable rejection reason
    raw_row: str             # the original row, serialized, for debugging


class RejectedRecordWriter:
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self._rows: list[RejectedRecord] = []

    def write(self, record: RejectedRecord) -> None:
        self._rows.append(record)

    def count(self) -> int:
        return len(self._rows)

    def flush(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["source", "resource_type", "row_number", "reason", "raw_row"]
        with open(self.output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self._rows:
                writer.writerow(asdict(r))
