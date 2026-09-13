"""
Real ingestion test: reads projext/data/source_a/patients.csv and runs
every row through resolve_patient_identity(), committing for real.

This intentionally reads the CSV directly rather than going through
Person 1's adapter, so it can run standalone while you're testing your
own storage layer in isolation. Once Person 2/5 wire the full pipeline
together, standardized_records writes will come from the FHIR-mapped
output instead -- this script is for proving identity resolution works
against real data right now.
"""

import csv
from pathlib import Path

from db import get_connection
from identity import resolve_patient_identity

# Adjust this if your data lives somewhere else.
SOURCE_A_PATIENTS_CSV = Path(__file__).resolve().parent.parent / "data" / "source_a" / "patients.csv"


def run():
    conn = get_connection()
    cur = conn.cursor()

    inserted_or_matched = 0
    skipped = 0

    with open(SOURCE_A_PATIENTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_number, raw_row in enumerate(reader, start=1):
            provider_patient_id = raw_row.get("Id", "")
            raw_ssn = raw_row.get("SSN", "")
            name = f"{raw_row.get('FIRST', '')} {raw_row.get('LAST', '')}".strip() or None
            birthdate = raw_row.get("BIRTHDATE") or None
            gender = raw_row.get("GENDER") or None

            try:
                healthsync_id = resolve_patient_identity(
                    cur,
                    source_provider="source_a",
                    provider_patient_id=provider_patient_id,
                    raw_ssn=raw_ssn,
                    name=name,
                    date_of_birth=birthdate,
                    gender=gender,
                )
                inserted_or_matched += 1
                if row_number <= 5:
                    print(f"Row {row_number}: {provider_patient_id} -> {healthsync_id}")
            except ValueError as e:
                skipped += 1
                print(f"Row {row_number} SKIPPED: {e}")

    conn.commit()  # real commit this time -- data will persist
    cur.close()
    conn.close()

    print(f"\nDone. {inserted_or_matched} patients resolved, {skipped} skipped.")


if __name__ == "__main__":
    run()
