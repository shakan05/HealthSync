"""
Internal normalized schema for the ingestion & validation layer.

This is the shared contract both Source A (Synthea) and Source B
(Patient Records 100K) adapters must produce. Person 2 (FHIR Standardization)
builds their mapping against these field names, not the raw CSV columns.

Design notes:
- Every resource that references a patient uses the field name "PATIENT".
- Every resource that references an encounter uses the field name "ENCOUNTER".
- The `patients` resource's own identifier is "PATIENT_ID" (not "PATIENT") to
  avoid confusing "this row's ID" with "the patient this row references".
- Same pattern for `encounters` -> "ENCOUNTER_ID".
- Clinical event resources use START/STOP where Synthea provides a range,
  or DATE where Synthea provides a single timestamp (observations, immunizations).
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
import re


@dataclass
class ResourceConfig:
    resource_type: str

    # Fields that MUST be present and non-empty on every row.
    required_fields: list[str]

    # Fields that must parse as dates (empty string is allowed unless also required).
    date_fields: list[str]

    # Fields that must be numeric (empty string allowed unless also required).
    numeric_fields: list[str]

    # (field_name, referenced_resource_type) — field_name's value must exist
    # in the referenced resource's identity set, built during load.
    reference_fields: list[tuple[str, str]]

    # Field(s) forming the natural key used for duplicate detection.
    dup_key_fields: list[str]

    # field_name -> validator function(value, row) -> Optional[str] (error message, or None if OK)
    # `row` is passed so rules can be conditional on other fields (e.g. VALUE is only
    # required to be numeric when TYPE == "numeric").
    value_rules: dict[str, Callable[[str, dict], Optional[str]]] = field(default_factory=dict)

    # If set, this field's value becomes this resource's identity, registered for
    # other resources to reference (used by patients -> PATIENT_ID, encounters -> ENCOUNTER_ID).
    identity_field: Optional[str] = None


def _allowed_values(allowed: set[str], field_label: str):
    def check(value: str, row: dict) -> Optional[str]:
        if value and value not in allowed:
            return f"{field_label} '{value}' not in allowed set {sorted(allowed)}"
        return None
    return check


def _observation_value_check(value: str, row: dict) -> Optional[str]:
    # VALUE only needs to be numeric when TYPE says it should be; text/coded
    # observations (TYPE == "text") are allowed to hold non-numeric strings.
    if row.get("TYPE") == "numeric" and value:
        try:
            float(value)
        except ValueError:
            return f"VALUE '{value}' is not numeric but TYPE='numeric'"
    return None


GENDER_CHECK = _allowed_values({"M", "F"}, "GENDER")

def _icd10_check(value: str, row: dict) -> Optional[str]:
    # Lightweight ICD-10-CM shape check (not a real terminology lookup):
    # one letter, two digits, optional decimal + up to 4 alphanumerics.
    # e.g. E78.5, N18.3, I10, M19.90
    if not value:
        return None
    if not re.match(r"^[A-TV-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$", value):
        return f"CODE '{value}' does not look like a valid ICD-10-CM code"
    return None

# Load order matters: patients -> encounters -> (conditions, medications,
# observations, procedures) -> allergies. Reference validation depends on
# earlier resources' identity sets already being built.
LOAD_ORDER = [
    "patients",
    "encounters",
    "conditions",
    "medications",
    "observations",
    "procedures",
    "allergies",
]

RESOURCE_CONFIGS: dict[str, ResourceConfig] = {
    "patients": ResourceConfig(
        resource_type="patients",
        required_fields=["PATIENT_ID", "BIRTHDATE", "GENDER"],
        date_fields=["BIRTHDATE", "DEATHDATE"],
        numeric_fields=[],
        reference_fields=[],
        dup_key_fields=["PATIENT_ID"],
        value_rules={"GENDER": GENDER_CHECK},
        identity_field="PATIENT_ID",
    ),
    "encounters": ResourceConfig(
        resource_type="encounters",
        required_fields=["ENCOUNTER_ID", "PATIENT", "START", "ENCOUNTERCLASS", "CODE"],
        date_fields=["START", "STOP"],
        numeric_fields=["BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST", "PAYER_COVERAGE"],
        reference_fields=[("PATIENT", "patients")],
        dup_key_fields=["ENCOUNTER_ID"],
        identity_field="ENCOUNTER_ID",
    ),
    "conditions": ResourceConfig(
        resource_type="conditions",
        required_fields=["PATIENT", "CODE", "START"],  # ENCOUNTER optional per Section 4.5
        # of the research doc: required for Allergy only, optional-but-must-exist-if-present
        # for Condition/MedicationRequest/Observation/Procedure.
        date_fields=["START", "STOP"],
        numeric_fields=[],
        reference_fields=[("PATIENT", "patients"), ("ENCOUNTER", "encounters")],
        dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "START"],
    ),
    "medications": ResourceConfig(
        resource_type="medications",
        required_fields=["PATIENT", "CODE", "START"],  # ENCOUNTER optional, see conditions above
        date_fields=["START", "STOP"],
        numeric_fields=["BASE_COST", "PAYER_COVERAGE", "DISPENSES", "TOTALCOST"],
        reference_fields=[("PATIENT", "patients"), ("ENCOUNTER", "encounters")],
        # STOP included (not just PATIENT/ENCOUNTER/CODE/START): Synthea sometimes
        # logs a same-day reissue/correction of a prescription (e.g. immediately
        # discontinued, then re-ordered with a different STOP/DISPENSES). That's a
        # real clinical event the contradiction-detection system needs to see, not
        # a duplicate row to silently collapse.
        dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "START", "STOP"],
    ),
    "observations": ResourceConfig(
        resource_type="observations",
        required_fields=["PATIENT", "CODE", "DATE"],  # ENCOUNTER intentionally NOT required:
        # Synthea emits patient-level yearly metrics (QALY/DALY) with no encounter link.
        # These are real clinical facts, not malformed rows — rejecting them would
        # silently destroy data the contradiction-detection system downstream needs.
        date_fields=["DATE"],
        numeric_fields=[],  # VALUE is conditionally numeric only when TYPE == "numeric"; handled in custom rule
        reference_fields=[("PATIENT", "patients"), ("ENCOUNTER", "encounters")],
        dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "DATE"],
        value_rules={"VALUE": _observation_value_check},
    ),
    "procedures": ResourceConfig(
        resource_type="procedures",
        required_fields=["PATIENT", "CODE", "START"],  # ENCOUNTER optional, see conditions above
        date_fields=["START", "STOP"],
        numeric_fields=["BASE_COST"],
        reference_fields=[("PATIENT", "patients"), ("ENCOUNTER", "encounters")],
        dup_key_fields=["PATIENT", "ENCOUNTER", "CODE", "START"],
    ),
    "allergies": ResourceConfig(
        resource_type="allergies",
        required_fields=["PATIENT", "ENCOUNTER", "CODE", "START"],
        date_fields=["START", "STOP"],
        numeric_fields=[],
        reference_fields=[("PATIENT", "patients"), ("ENCOUNTER", "encounters")],
        dup_key_fields=["PATIENT", "ENCOUNTER", "CODE"],
    ),
}
