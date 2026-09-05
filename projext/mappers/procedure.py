"""
FHIR Procedure resource mapper.

Maps Person 1's validated, normalized "procedures" records (schema.py)
into FHIR Procedure JSON (Source A / Synthea only).

Design decisions:
1. Status: FHIR Procedure `status` is required; defaulted to "completed" since 
   these represent historical records of performed procedures.
2. Coding systems: Source A uses SNOMED-CT codes for procedures.
3. Encounter linkage: ENCOUNTER is linked via reference if present.
4. Resource id is intentionally left for Person 3.
"""

from typing import Optional


SNOMED_PROCEDURE_SYSTEM = "http://snomed.info/sct"


def _patient_ref(source: str, patient_id: str) -> dict:
    return {"reference": f"Patient/{source}-{patient_id}"}


def _encounter_ref(source: str, encounter_id: str) -> Optional[dict]:
    if not encounter_id:
        return None
    return {"reference": f"Encounter/{source}-{encounter_id}"}


def _map_procedure_coding(row: dict) -> dict:
    code = row.get("CODE", "")
    description = row.get("DESCRIPTION", "")

    coding = {"system": SNOMED_PROCEDURE_SYSTEM, "code": code}
    if description:
        coding["display"] = description

    concept = {"coding": [coding]}
    if description:
        concept["text"] = description
    return concept


def map_procedure(row: dict, source: str) -> dict:
    """
    row: a single normalized "procedures" record from Source A.
    source: "source_a" (Source B lacks procedures data).

    Returns a FHIR Procedure resource dict.
    """
    if source != "source_a":
        raise ValueError(f"Procedure mapping is only supported for 'source_a', got '{source}'")

    resource = {
        "resourceType": "Procedure",
        "status": "completed",
        "code": _map_procedure_coding(row),
        "subject": _patient_ref(source, row.get("PATIENT", "")),
    }

    encounter_ref = _encounter_ref(source, row.get("ENCOUNTER", ""))
    if encounter_ref:
        resource["encounter"] = encounter_ref

    performed_date = row.get("DATE", "") or row.get("START", "")
    if performed_date:
        resource["performedDateTime"] = performed_date

    return resource