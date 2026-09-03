"""
Source Adapter B: Patient Records 100K, 15 Conditions dataset.

Confirmed real file structures (from actual uploaded samples, not the
research doc's earlier guesses):

  patients.csv     patient_id, age, sex, bmi, systolic_bp, diastolic_bp,
                    heart_rate, temperature_f, smoking_status, alcohol_use,
                    exercise_level, insurance_type, charlson_index,
                    dx_hypertension, dx_type2_diabetes, dx_hyperlipidemia,
                    dx_obesity, dx_coronary_artery_disease, dx_heart_failure,
                    dx_atrial_fibrillation, dx_chronic_kidney_disease,
                    dx_copd, dx_asthma, dx_depression, dx_anxiety,
                    dx_hypothyroidism, dx_osteoarthritis, dx_type1_diabetes

  diagnoses.csv     patient_id, visit_date, visit_type, primary_diagnosis,
                    primary_icd10, secondary_diagnoses, secondary_icd10s,
                    provider_specialty

  medications.csv   patient_id, medication, dose, unit, frequency,
                    indication, start_date, duration_days, is_generic,
                    adherence_pct

  lab_results.csv   patient_id, test_date, test_name, value, unit, reference_low,
                    reference_high, flag, is_abnormal, delta_from_normal
                    (confirmed from real header row)

  outcomes.csv      patient_id, admission_date, discharge_date,
                    length_of_stay_days, icu_admission, icu_days,
                    in_hospital_death, discharge_disposition,
                    readmitted_30d, days_to_readmission, primary_drg,
                    total_charges_usd

Key structural facts that shape this adapter (all confirmed from real data):
  - patients.csv has NO SSN, NO name -- just patient_id. There is genuinely
    no identity key here. Per the team's own design decision, every Source B
    patient row (and everything that references it) is rejected with
    reason "no identity key" until a fallback key is chosen. This adapter
    does NOT invent one.
  - patients.csv has no BIRTHDATE, only age -- approximated below, see
    _approximate_birthdate().
  - medications.csv and lab_results.csv have no coded values (no RxNorm/
    LOINC) -- the raw name is used as CODE, tagged as uncoded in
    resource_json so nothing downstream mistakes it for a real code.
  - diagnoses.csv and medications.csv have no encounter linkage at all --
    relies on the schema fix making ENCOUNTER optional for these resources.
  - outcomes.csv has no ENCOUNTER_ID of its own -- synthesized as
    f"{patient_id}_{admission_date}" (unique per hospitalization).
  - outcomes.csv has no CODE -- primary_drg (DRG code) used as the
    Encounter's CODE, the closest real standardized code available.
"""

import csv
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from schema import RESOURCE_CONFIGS, _icd10_check
from validators import validate_row, ValidationContext
from rejected import RejectedRecordWriter, RejectedRecord

SOURCE_NAME = "source_b"

# Source B's own load order (no procedures/allergies files exist for this source).
# patients -> encounters -> conditions -> medications -> observations,
# matching Section 4.6 of the research doc.
SOURCE_B_LOAD_ORDER = ["patients", "encounters", "conditions", "medications", "observations"]

# raw filename (without .csv) -> resource_type
FILE_TO_RESOURCE = {
    "patients": "patients",
    "outcomes": "encounters",
    "diagnoses": "conditions",
    "medications": "medications",
    "lab_results": "observations",
}
RESOURCE_TO_FILE = {v: k for k, v in FILE_TO_RESOURCE.items()}

# Conditions get a stricter CODE check for Source B: real ICD-10-CM format
# (Synthea's own "conditions" config is untouched -- it uses SNOMED numeric
# codes and would fail this check, which is exactly why this override lives
# here rather than in the shared schema).
#
# dup_key_fields is ALSO overridden here: diagnoses.csv has no ENCOUNTER to
# distinguish two real visits on the same day. Verified against real data --
# same patient/date/code pairs that looked like duplicates turned out to be
# genuinely different visits (e.g. an outpatient visit and a same-day
# telehealth follow-up, or an ER visit followed by same-day inpatient
# admission) with different visit_type/provider_specialty. Both raw fields
# survive normalization (normalize functions start from dict(raw)), so they're
# safe to reference here even though they aren't part of the shared schema.
CONDITIONS_CONFIG_B = replace(
    RESOURCE_CONFIGS["conditions"],
    value_rules={**RESOURCE_CONFIGS["conditions"].value_rules, "CODE": _icd10_check},
    dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "START", "visit_type", "provider_specialty"],
)

# medications.csv also has no ENCOUNTER. "indication" distinguishes legitimate
# same-day re-prescriptions of the same drug for a different reason.
MEDICATIONS_CONFIG_B = replace(
    RESOURCE_CONFIGS["medications"],
    dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "START", "STOP", "indication"],
)

# lab_results.csv also has no ENCOUNTER. Including VALUE means two readings
# of the same test on the same day (e.g. a redraw) aren't collapsed unless
# they also have the literal same result -- much closer to "true duplicate."
OBSERVATIONS_CONFIG_B = replace(
    RESOURCE_CONFIGS["observations"],
    dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "DATE", "VALUE"],
)

RESOURCE_CONFIGS_B = {
    "patients": RESOURCE_CONFIGS["patients"],
    "encounters": RESOURCE_CONFIGS["encounters"],
    "conditions": CONDITIONS_CONFIG_B,
    "medications": MEDICATIONS_CONFIG_B,
    "observations": OBSERVATIONS_CONFIG_B,
}

# Reference date used to approximate BIRTHDATE from age (patients.csv has no DOB).
# Chosen as roughly the midpoint/upper edge of the observed date range (2018-2024)
# across diagnoses/medications/outcomes samples. This is a known approximation,
# accurate to within about a year -- flagged in resource_json, not silently trusted.
AGE_REFERENCE_YEAR = 2024


def _convert_date(value: str) -> str:
    """M/D/YYYY -> YYYY-MM-DD. Returns '' unchanged if empty or unparseable."""
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return value  # leave as-is; validate_row's date check will catch it


def _approximate_birthdate(age_str: str) -> str:
    if not age_str:
        return ""
    try:
        age = int(age_str)
    except ValueError:
        return ""
    birth_year = AGE_REFERENCE_YEAR - age
    return f"{birth_year}-01-01"


def _add_days(date_str: str, days_str: str) -> str:
    """date_str already normalized to YYYY-MM-DD. Returns '' if inputs are bad."""
    if not date_str or not days_str:
        return ""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days = float(days_str)
        result = dt.fromordinal(dt.toordinal() + int(days))
        return result.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return ""


def _normalize_patients(raw: dict) -> dict:
    row = dict(raw)
    row["PATIENT_ID"] = raw.get("patient_id", "")
    row["GENDER"] = raw.get("sex", "")
    row["BIRTHDATE"] = _approximate_birthdate(raw.get("age", ""))
    row["_birthdate_is_approximated"] = "true"  # flag for resource_json, not a schema field
    row["DEATHDATE"] = ""  # not tracked at patient level in this source
    return row


def _normalize_conditions(raw: dict) -> dict:
    row = dict(raw)
    row["PATIENT"] = raw.get("patient_id", "")
    row["ENCOUNTER"] = ""  # no linkage available; now optional per schema fix
    row["CODE"] = raw.get("primary_icd10", "")
    row["DESCRIPTION"] = raw.get("primary_diagnosis", "")
    row["START"] = _convert_date(raw.get("visit_date", ""))
    row["STOP"] = ""
    row["CODE_SYSTEM"] = "ICD-10-CM"
    # secondary_diagnoses / secondary_icd10s intentionally NOT exploded into
    # separate Condition rows -- kept as raw context for Person 2 to decide
    # how to model. Flagging as an open item, not a silent decision.
    return row


def _normalize_medications(raw: dict) -> dict:
    row = dict(raw)
    row["PATIENT"] = raw.get("patient_id", "")
    row["ENCOUNTER"] = ""
    row["CODE"] = raw.get("medication", "")
    row["CODE_SYSTEM"] = "drug_name_uncoded"  # explicit: NOT a real RxNorm code
    row["DESCRIPTION"] = raw.get("medication", "")
    start = _convert_date(raw.get("start_date", ""))
    row["START"] = start
    row["STOP"] = _add_days(start, raw.get("duration_days", ""))
    return row


def _normalize_observations(raw: dict) -> dict:
    row = dict(raw)
    row["PATIENT"] = raw.get("patient_id", "")
    row["ENCOUNTER"] = ""  # lab_results.csv has no encounter linkage
    row["DATE"] = _convert_date(raw.get("test_date", ""))
    row["CODE"] = raw.get("test_name", "")
    row["CODE_SYSTEM"] = "lab_test_name_uncoded"  # NOT a real LOINC code
    row["DESCRIPTION"] = raw.get("test_name", "")
    row["VALUE"] = raw.get("value", "")
    row["UNITS"] = raw.get("unit", "")
    row["TYPE"] = "numeric"  # all Source B lab values are numeric
    row["CATEGORY"] = "laboratory"
    return row


def _normalize_encounters(raw: dict) -> dict:
    row = dict(raw)
    patient_id = raw.get("patient_id", "")
    admission_date = raw.get("admission_date", "")
    row["PATIENT"] = patient_id
    row["ENCOUNTER_ID"] = f"{patient_id}_{admission_date}" if patient_id and admission_date else ""
    row["START"] = _convert_date(admission_date)
    row["STOP"] = _convert_date(raw.get("discharge_date", ""))
    row["ENCOUNTERCLASS"] = "inpatient"  # every outcomes.csv row is a hospitalization
    row["CODE"] = raw.get("primary_drg", "")
    row["CODE_SYSTEM"] = "DRG"
    row["DESCRIPTION"] = f"DRG {raw.get('primary_drg', '')}".strip()
    return row


NORMALIZERS = {
    "patients": _normalize_patients,
    "encounters": _normalize_encounters,
    "conditions": _normalize_conditions,
    "medications": _normalize_medications,
    "observations": _normalize_observations,
}


def _sniff_delimiter(filepath: Path) -> str:
    with open(filepath, newline="", encoding="utf-8") as f:
        sample = f.readline()
    return "\t" if "\t" in sample else ","


def run_source_b(data_dir: str, rejected_writer: RejectedRecordWriter) -> dict[str, list[dict]]:
    """
    Loads all Source B files in load order, validating every row against
    RESOURCE_CONFIGS_B (Source B's variant of the shared schema). Returns
    dict of resource_type -> list of valid normalized rows.
    """
    ctx = ValidationContext()  # separate from Source A's -- Source B references
    # its own patients/encounters, not Synthea's.
    valid_records: dict[str, list[dict]] = {rt: [] for rt in SOURCE_B_LOAD_ORDER}
    summary = {rt: {"valid": 0, "rejected": 0} for rt in SOURCE_B_LOAD_ORDER}

    for resource_type in SOURCE_B_LOAD_ORDER:
        filename = f"{RESOURCE_TO_FILE[resource_type]}.csv"
        filepath = Path(data_dir) / filename
        if not filepath.exists():
            print(f"  [source_b] WARNING: {filename} not found, skipping")
            continue

        config = RESOURCE_CONFIGS_B[resource_type]
        normalize = NORMALIZERS[resource_type]
        delimiter = _sniff_delimiter(filepath)

        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row_number, raw_row in enumerate(reader, start=1):
                normalized = normalize(raw_row)
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
            f"  [source_b] {resource_type}: "
            f"{summary[resource_type]['valid']} valid, "
            f"{summary[resource_type]['rejected']} rejected"
        )

    return valid_records