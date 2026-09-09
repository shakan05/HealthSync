"""
Full end-to-end test of your storage layer against real Source A data:
encounters.csv and conditions.csv -> Person 2's mappers -> your identity
resolution + standardized_records storage.

Run this AFTER ingest_patients_source_a.py, since it depends on
patient_id_mapping already being populated.
"""

import csv
import sys
from pathlib import Path

# Make projext/mappers importable (mirrors how the adapters import schema.py).
PROJEXT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJEXT_DIR / "mappers"))

from encounter import map_encounter
from condition import map_condition

from db import get_connection
from write_records import write_standardized_record

DATA_DIR = PROJEXT_DIR / "data" / "source_a"


def _normalize_encounter_row(raw_row: dict) -> dict:
    row = dict(raw_row)
    row["ENCOUNTER_ID"] = row.pop("Id", "")
    return row


def run():
    conn = get_connection()
    cur = conn.cursor()

    # --- Encounters ---
    encounters_processed = 0
    encounters_skipped = 0
    with open(DATA_DIR / "encounters.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_number, raw_row in enumerate(reader, start=1):
            row = _normalize_encounter_row(raw_row)
            try:
                resource = map_encounter(row, "source_a")
                resource_id = write_standardized_record(
                    cur, resource, row, "encounters", "source_a",
                    event_date=row.get("START"),
                )
                encounters_processed += 1
                if row_number <= 3:
                    print(f"Encounter row {row_number}: stored as {resource_id}")
            except ValueError as e:
                encounters_skipped += 1
                print(f"Encounter row {row_number} SKIPPED: {e}")

    print(f"Encounters: {encounters_processed} stored, {encounters_skipped} skipped.\n")

    # --- Conditions ---
    conditions_processed = 0
    conditions_skipped = 0
    with open(DATA_DIR / "conditions.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=1):
            try:
                resource = map_condition(row, "source_a")
                resource_id = write_standardized_record(
                    cur, resource, row, "conditions", "source_a",
                    event_date=row.get("START"),
                )
                conditions_processed += 1
                if row_number <= 3:
                    print(f"Condition row {row_number}: stored as {resource_id}")
            except ValueError as e:
                conditions_skipped += 1
                print(f"Condition row {row_number} SKIPPED: {e}")

    print(f"Conditions: {conditions_processed} stored, {conditions_skipped} skipped.")

    conn.commit()
    cur.close()
    conn.close()
    print("\nDone. Data committed to standardized_records + provenance.")


if __name__ == "__main__":
    run()
