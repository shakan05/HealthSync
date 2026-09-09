"""
Finishes off Source A: medications, observations, procedures, allergies.
(patients, encounters, conditions were already done in the previous scripts.)

Same pattern throughout: read CSV row -> Person 2's map_*() -> your
write_standardized_record(). Written as one generic loop since all four
resource types follow the identical shape.
"""

import csv
import sys
from pathlib import Path

PROJEXT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJEXT_DIR / "mappers"))

from medication_request import map_medication_request
from observation import map_observation
from procedure import map_procedure
from allergy import map_allergy

from db import get_connection
from write_records import write_standardized_record

DATA_DIR = PROJEXT_DIR / "data" / "source_a"

# (csv filename, schema.py resource_type key, mapper function, event_date field)
RESOURCE_JOBS = [
    ("medications.csv", "medications", map_medication_request, "START"),
    ("observations.csv", "observations", map_observation, "DATE"),
    ("procedures.csv", "procedures", map_procedure, "START"),
    ("allergies.csv", "allergies", map_allergy, "START"),
]


def run():
    conn = get_connection()
    cur = conn.cursor()

    for filename, resource_type, map_func, date_field in RESOURCE_JOBS:
        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"{filename} not found, skipping.\n")
            continue

        stored = 0
        skipped = 0
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_number, row in enumerate(reader, start=1):
                try:
                    resource = map_func(row, "source_a")
                    resource_id = write_standardized_record(
                        cur, resource, row, resource_type, "source_a",
                        event_date=row.get(date_field),
                    )
                    stored += 1
                    if row_number <= 3:
                        print(f"{resource_type} row {row_number}: stored as {resource_id}")
                except ValueError as e:
                    skipped += 1
                    print(f"{resource_type} row {row_number} SKIPPED: {e}")

        print(f"{resource_type}: {stored} stored, {skipped} skipped.\n")

    conn.commit()
    cur.close()
    conn.close()
    print("Done. Source A is now fully ingested.")


if __name__ == "__main__":
    run()
