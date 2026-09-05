"""
FHIR Condition resource mapper.

Maps Person 1's validated, normalized "conditions" records (schema.py)
into FHIR Condition JSON, for both Source A (Synthea) and Source B
(Patient Records 100K diagnoses.csv).

Design decisions:
1. Coding systems: Source A uses SNOMED-CT codes for conditions. Source B 
   uses ICD-10-CM codes (explicitly flagged as ICD-10-CM by Source B adapter).
2. Encounter linkage: ENCOUNTER is optional for conditions in the shared schema; 
   if present, it is linked via reference.
3. Clinical status: Inferred as "active" if STOP is missing, or "resolved" 
   if a STOP date is present.
4. Resource id is intentionally left for Person 3.
"""

from typing import Optional


SNOMED_SYSTEM = "http://snomed.info/sct"
ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"


def _patient_ref(source: str, patient_id: str) -> dict:
    return {"reference": f"Patient/{source}-{patient_id}"}


def _encounter_ref(source: str, encounter_id: str) -> Optional[dict]:
    if not encounter_id:
        return None
    return {"reference": f"Encounter/{source}-{encounter_id}"}


def _map_condition_coding(row: dict) -> dict:
    code = row.get("CODE", "")
    description = row.get("DESCRIPTION", "")
    code_system = row.get("CODE_SYSTEM", "")

    # Source B sets CODE_SYSTEM = "ICD-10-CM", otherwise default to SNOMED for Synthea
    system = ICD10_SYSTEM if code_system == "ICD-10-CM" else SNOMED_SYSTEM

    coding = {"system": system, "code": code}
    if description:
        coding["display"] = description

    concept = {"coding": [coding]}
    if description:
        concept["text"] = description
    return concept


def _map_clinical_status(stop: str) -> dict:
    """
    Inferred status: active if no stop date, resolved if stop date exists.
    """
    status_code = "resolved" if stop else "active"
    return {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": status_code
        }]
    }


def map_condition(row: dict, source: str) -> dict:
    """
    row: a single normalized "conditions" record from either source.
    source: "source_a" or "source_b"

    Returns a FHIR Condition resource dict.
    """
    if source not in ("source_a", "source_b"):
        raise ValueError(f"unknown source '{source}' -- must be 'source_a' or 'source_b'")

    resource = {
        "resourceType": "Condition",
        "clinicalStatus": _map_clinical_status(row.get("STOP", "")),
        "code": _map_condition_coding(row),
        "subject": _patient_ref(source, row.get("PATIENT", "")),
    }

    encounter_ref = _encounter_ref(source, row.get("ENCOUNTER", ""))
    if encounter_ref:
        resource["encounter"] = encounter_ref

    onset = {}
    if row.get("START"):
        onset["onsetDateTime"] = row["START"]
    if onset:
        resource.update(onset)

    abatement = {}
    if row.get("STOP"):
        abatement["abatementDateTime"] = row["STOP"]
    if abatement:
        resource.update(abatement)

    return resource