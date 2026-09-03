"""
Source Adapter A: Synthea.

Synthea's raw column names are already close to the internal schema (it's
literally where PATIENT/CODE/START/STOP as internal names came from). The
only renames needed are the two identity columns, which are called "Id" in
the raw files but need resource-specific names internally so they don't
collide with the "PATIENT" / "ENCOUNTER" *reference* fields used elsewhere.
"""

import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from schema import RESOURCE_CONFIGS, LOAD_ORDER
from validators import validate_row, ValidationContext
from rejected import RejectedRecordWriter, RejectedRecord

SOURCE_NAME = "source_a"

# raw filename (without .csv) -> resource_type key in RESOURCE_CONFIGS
FILE_TO_RESOURCE = {
    "patients": "patients",
    "encounters": "encounters",
    "conditions": "conditions",
    "medications": "medications",
    "observations": "observations",
    "procedures": "procedures",
    "allergies": "allergies",
}

# Column renames per resource type: raw Synthea column -> internal field name.
# Any column not listed here is passed through unchanged.
COLUMN_RENAMES = {
    "patients": {"Id": "PATIENT_ID"},
    "encounters": {"Id": "ENCOUNTER_ID"},
    "conditions": {},
    "medications": {},
    "observations": {},
    "procedures": {},
    "allergies": {},
}


def _normalize_row(raw_row: dict, resource_type: str) -> dict:
    renames = COLUMN_RENAMES[resource_type]
    normalized = {}
    for k, v in raw_row.items():
        key = renames.get(k, k)
        normalized[key] = v if v is not None else ""
    return normalized


def run_source_a(data_dir: str, rejected_writer: RejectedRecordWriter) -> dict[str, list[dict]]:
    """
    Loads all Source A files in the required load order, validating every
    row. Returns dict of resource_type -> list of valid normalized rows.
    Rejected rows are pushed into `rejected_writer`, never dropped silently.
    """
    ctx = ValidationContext()
    valid_records: dict[str, list[dict]] = {rt: [] for rt in LOAD_ORDER}
    summary = {rt: {"valid": 0, "rejected": 0} for rt in LOAD_ORDER}

    for resource_type in LOAD_ORDER:
        filename = f"{resource_type}.csv"
        filepath = Path(data_dir) / filename
        if not filepath.exists():
            print(f"  [source_a] WARNING: {filename} not found, skipping")
            continue

        config = RESOURCE_CONFIGS[resource_type]

        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_number, raw_row in enumerate(reader, start=1):
                normalized = _normalize_row(raw_row, resource_type)
                is_valid, reason = validate_row(normalized, config, ctx)

                if is_valid:
                    valid_records[resource_type].append(normalized)
                    summary[resource_type]["valid"] += 1
                else:
                    rejected_writer.write(
                        RejectedRecord(
                            source=SOURCE_NAME,
                            resource_type=resource_type,
                            row_number=row_number,
                            reason=reason,
                            raw_row=str(raw_row),
                        )
                    )
                    summary[resource_type]["rejected"] += 1

        print(
            f"  [source_a] {resource_type}: "
            f"{summary[resource_type]['valid']} valid, "
            f"{summary[resource_type]['rejected']} rejected"
        )

    return valid_records
