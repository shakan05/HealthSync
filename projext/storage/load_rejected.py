"""
Loads Person 1's rejected_records.csv into the rejected_records table so it
can be queried alongside everything else in Postgres.

This does NOT replace the CSV -- ingestion keeps writing to it as before.
Run this script whenever you want the table to reflect the latest CSV
contents (e.g. after a pipeline run, or before a demo).

Usage:
    python load_rejected.py path/to/rejected_records.csv
"""

import csv
import json
import sys

from db import get_connection


def load_rejected_csv(csv_path: str) -> None:
    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # raw_row in the CSV is a stringified dict (from RejectedRecord's
            # str(raw_row) in the adapters). Try to store it as real JSONB;
            # fall back to wrapping it as a string if it isn't valid JSON.
            raw_row_value = row.get("raw_row", "")
            try:
                raw_row_json = json.loads(raw_row_value)
            except (json.JSONDecodeError, TypeError):
                raw_row_json = {"raw": raw_row_value}

            cur.execute(
                """
                INSERT INTO rejected_records (source, row_number, reason, raw_row)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    row.get("source"),
                    int(row["row_number"]) if row.get("row_number") else None,
                    row.get("reason"),
                    json.dumps(raw_row_json),
                ),
            )
            inserted += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Loaded {inserted} rejected records from {csv_path} into the database.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python load_rejected.py path/to/rejected_records.csv")
        sys.exit(1)

    load_rejected_csv(sys.argv[1])
