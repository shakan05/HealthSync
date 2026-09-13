"""
DB-backed replacement for RejectedRecordWriter, per rejected.py's own
docstring invitation: "Swap this class's flush/write internals for a real
DB insert once Person 3's Postgres schema exists."

Same interface (write(), count(), flush()) as the CSV version, so the
adapters don't need to change at all -- they just get handed this instead.
"""

import json

from rejected import RejectedRecordWriter, RejectedRecord


class DbRejectedRecordWriter(RejectedRecordWriter):
    def __init__(self, cur):
        # Deliberately skip the CSV-path __init__ (no output_path needed).
        self.cur = cur
        self._rows: list[RejectedRecord] = []

    def flush(self) -> None:
        for r in self._rows:
            self.cur.execute(
                """
                INSERT INTO rejected_records (source, resource_type, row_number, reason, raw_row)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (r.source, r.resource_type, r.row_number, r.reason, json.dumps(r.raw_row)),
            )
