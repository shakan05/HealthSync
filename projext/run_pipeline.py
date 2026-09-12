"""
Main end-to-end pipeline execution script.
Orchestrates:
  1. Person 1: Ingestion & Validation (Source A & Source B)
  2. Person 2: FHIR Standardization & Mapping
  3. Person 3: Identity Resolution + Storage (Postgres, replaces the
     earlier per-patient-JSON output now that Person 3's storage layer
     is built and verified)
"""

from pathlib import Path

# Person 1 Imports
from adapters.source_a_synthea import run_source_a

# Person 2 Imports
from mappers.patient import map_patient
from mappers.encounter import map_encounter
from mappers.medication_request import map_medication_request
from mappers.condition import map_condition
from mappers.observation import map_observation
from mappers.procedure import map_procedure
from mappers.allergy import map_allergy

# Person 3 Imports
from storage.db import get_connection
from storage.identity import resolve_patient_identity
from storage.write_records import (
    write_patient_resource,
    build_patient_mapping_cache,
    prepare_batch_row,
    write_standardized_records_batch,
)
from storage.db_rejected_writer import DbRejectedRecordWriter

import os

BASE_DIR = Path(__file__).resolve().parent

# For quick local testing without touching real data: set env var
# HEALTHSYNC_DATA_DIR to point at a small sample folder instead. Leave unset
# for normal use -- defaults to the real projext/data folder, unchanged.
DATA_ROOT = Path(os.environ.get("HEALTHSYNC_DATA_DIR", str(BASE_DIR / "data")))

# (schema.py resource_type key, mapper function, event_date field)
RESOURCE_JOBS = [
    ("encounters", map_encounter, "START"),
    ("conditions", map_condition, "START"),
    ("medications", map_medication_request, "START"),
    ("observations", map_observation, "DATE"),
    ("procedures", map_procedure, "START"),
    ("allergies", map_allergy, "START"),
]


def _ingest_patients(cur, valid_records: dict, source: str) -> int:
    stored, skipped = 0, 0
    for row in valid_records.get("patients", []):
        try:
            healthsync_id = resolve_patient_identity(
                cur, source, row.get("PATIENT_ID", ""),
                raw_ssn=row.get("SSN", ""),
                name=f"{row.get('FIRST', '')} {row.get('LAST', '')}".strip() or None,
                date_of_birth=row.get("BIRTHDATE") or None,
                gender=row.get("GENDER") or None,
            )
            # Also store the full FHIR Patient resource (preserves fields/
            # extensions the flat `patients` table can't hold).
            patient_resource = map_patient(row, source)
            write_patient_resource(cur, patient_resource, healthsync_id, source)
            stored += 1
        except ValueError as e:
            skipped += 1
            print(f"  patients SKIPPED: {e}")
    print(f"  patients: {stored} stored, {skipped} skipped")
    cur.connection.commit()  # commit patients before moving on to resources
    return stored


def _ingest_resources(cur, valid_records: dict, source: str) -> None:
    # One bulk query instead of one lookup per row -- see write_records.py.
    mapping_cache = build_patient_mapping_cache(cur, source)

    for resource_type, map_func, date_field in RESOURCE_JOBS:
        rows = valid_records.get(resource_type, [])
        prepared = []
        skipped = 0
        for row in rows:
            try:
                resource = map_func(row, source)
                prepared_row = prepare_batch_row(
                    row, resource, resource_type, source, mapping_cache,
                    event_date=row.get(date_field),
                )
                prepared.append(prepared_row)
            except ValueError as e:
                skipped += 1
                print(f"  {resource_type} SKIPPED: {e}")

        newly_stored = write_standardized_records_batch(cur, prepared)
        already_existed = len(prepared) - newly_stored
        print(
            f"  {resource_type}: {newly_stored} newly stored, "
            f"{already_existed} already existed, {skipped} skipped"
        )
        cur.connection.commit()  # commit after each resource type, not just at the very end --
        # if the run gets interrupted, you only lose progress on the CURRENT
        # resource type, not everything done so far.


def run_pipeline():
    print("=== Starting HealthSync End-to-End Pipeline ===\n")

    conn = get_connection()
    cur = conn.cursor()
    rejected_writer = DbRejectedRecordWriter(cur)

    print("=== Source A ===")
    valid_a = run_source_a(str(DATA_ROOT / "source_a"), rejected_writer)
    _ingest_patients(cur, valid_a, "source_a")
    _ingest_resources(cur, valid_a, "source_a")

    rejected_writer.flush()
    print(f"\nRejected rows written to rejected_records table: {rejected_writer.count()}")

    conn.commit()
    cur.close()
    conn.close()

    print("\n=== Pipeline Execution Complete: data stored in Postgres ===")


if __name__ == "__main__":
    run_pipeline()
