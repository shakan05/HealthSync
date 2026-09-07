"""
Main end-to-end pipeline execution script.
Orchestrates:
  1. Person 1: Ingestion & Validation (Source A & Source B)
  2. Person 2: FHIR Standardization & Mapping
  3. Writes one JSON file per patient (ready for Person 3 - Hashing & Storage)
"""

import json
import re
from pathlib import Path
from collections import defaultdict

# Person 1 Imports
from adapters.source_a_synthea import run_source_a
from adapters.source_b_patient_records100k import run_source_b
from rejected import RejectedRecordWriter

# Person 2 Imports
from mappers.patient import map_patient
from mappers.encounter import map_encounter
from mappers.medication_request import map_medication_request
from mappers.condition import map_condition
from mappers.observation import map_observation
from mappers.procedure import map_procedure
from mappers.allergy import map_allergy

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PATIENTS_DIR = OUTPUT_DIR / "patients"


def safe_filename(key: str) -> str:
    """Sanitize a patient key so it's safe to use as a filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", key)


def patient_key(row: dict, source: str, id_field: str) -> str:
    """Same key used in subject/patient references, e.g. 'source_a-abc123'."""
    patient_id = row.get(id_field, "") or "UNKNOWN"
    return f"{source}-{patient_id}"


def write_patient_files(patient_buckets: dict) -> None:
    """
    Writes one JSON file per patient: output/patients/<source>-<patient_id>.json
    Each file contains only that patient's own resources.
    """
    PATIENTS_DIR.mkdir(parents=True, exist_ok=True)

    for key, resources in patient_buckets.items():
        counts = defaultdict(int)
        for r in resources:
            counts[r.get("resourceType", "Unknown")] += 1

        bundle = {
            "patientKey": key,
            "resourceCounts": dict(counts),
            "resources": resources,
        }

        out_path = PATIENTS_DIR / f"{safe_filename(key)}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, default=str)

    print(f"-> Wrote {len(patient_buckets)} patient file(s) to: {PATIENTS_DIR}")


def run_pipeline():
    print("=== Starting HealthSync End-to-End Pipeline ===\n")

    # 1. Person 1: Ingestion & Validation
    rejected_writer = RejectedRecordWriter(str(OUTPUT_DIR / "rejected_records.csv"))

    print("Running Person 1 validation & ingestion (Source A - Synthea)...")
    valid_a = run_source_a(str(BASE_DIR / "data" / "source_a"), rejected_writer)

    print("Running Person 1 validation & ingestion (Source B - 100K Records)...")
    valid_b = run_source_b(str(BASE_DIR / "data" / "source_b"), rejected_writer)

    rejected_writer.flush()
    print(f"-> Ingestion complete. Rejected records written to: {rejected_writer.output_path}\n")

    # 2. Person 2: FHIR Standardization & Mapping
    print("Running Person 2 FHIR standardization...")

    patient_buckets = defaultdict(list)

    def add(resource, key):
        patient_buckets[key].append(resource)

    # --- Source A ---
    for row in valid_a.get("patients", []):
        add(map_patient(row, "source_a"), patient_key(row, "source_a", "PATIENT_ID"))

    for row in valid_a.get("encounters", []):
        add(map_encounter(row, "source_a"), patient_key(row, "source_a", "PATIENT"))

    for row in valid_a.get("conditions", []):
        add(map_condition(row, "source_a"), patient_key(row, "source_a", "PATIENT"))

    for row in valid_a.get("observations", []):
        add(map_observation(row, "source_a"), patient_key(row, "source_a", "PATIENT"))

    for row in valid_a.get("medications", []):
        add(map_medication_request(row, "source_a"), patient_key(row, "source_a", "PATIENT"))

    for row in valid_a.get("procedures", []):
        add(map_procedure(row, "source_a"), patient_key(row, "source_a", "PATIENT"))

    for row in valid_a.get("allergies", []):
        add(map_allergy(row, "source_a"), patient_key(row, "source_a", "PATIENT"))

    # --- Source B ---
    for row in valid_b.get("patients", []):
        add(map_patient(row, "source_b"), patient_key(row, "source_b", "PATIENT_ID"))

    for row in valid_b.get("encounters", []):
        add(map_encounter(row, "source_b"), patient_key(row, "source_b", "PATIENT"))

    for row in valid_b.get("conditions", []):
        add(map_condition(row, "source_b"), patient_key(row, "source_b", "PATIENT"))

    for row in valid_b.get("observations", []):
        add(map_observation(row, "source_b"), patient_key(row, "source_b", "PATIENT"))

    for row in valid_b.get("medications", []):
        add(map_medication_request(row, "source_b"), patient_key(row, "source_b", "PATIENT"))

    total_resources = sum(len(v) for v in patient_buckets.values())
    print(f"-> Generated {total_resources} FHIR resources across {len(patient_buckets)} patients.\n")

    # 3. Write one JSON file per patient
    print("Writing per-patient JSON files...")
    write_patient_files(patient_buckets)

    print("\n=== Pipeline Execution Complete (Ready for Person 3) ===")

    return patient_buckets


if __name__ == "__main__":
    run_pipeline()