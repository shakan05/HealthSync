"""
FHIR AllergyIntolerance resource mapper.

Maps Person 1's validated, normalized "allergies" records (schema.py)
into FHIR AllergyIntolerance JSON (Source A / Synthea only).

Design decisions:
1. Clinical & Verification Status: Defaulted to active and confirmed per Synthea specs.
2. Coding: Maps allergy code using SNOMED-CT.
3. Resource id is intentionally left for Person 3.
"""

from typing import Optional


SNOMED_ALLERGY_SYSTEM = "http://snomed.info/sct"


def _patient_ref(source: str, patient_id: str) -> dict:
    return {"reference": f"Patient/{source}-{patient_id}"}


def map_allergy(row: dict, source: str) -> dict:
    """
    row: a single normalized "allergies" record from Source A.
    source: "source_a" (Source B lacks allergies data).

    Returns a FHIR AllergyIntolerance resource dict.
    """
    if source != "source_a":
        raise ValueError(f"AllergyIntolerance mapping is only supported for 'source_a', got '{source}'")

    code = row.get("CODE", "")
    description = row.get("DESCRIPTION", "")

    coding = {"system": SNOMED_ALLERGY_SYSTEM, "code": code}
    if description:
        coding["display"] = description

    code_concept = {"coding": [coding]}
    if description:
        code_concept["text"] = description

    resource = {
        "resourceType": "AllergyIntolerance",
        "clinicalStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                "code": "active"
            }]
        },
        "verificationStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                "code": "confirmed"
            }]
        },
        "type": "allergy",
        "code": code_concept,
        "subject": _patient_ref(source, row.get("PATIENT", "")),
    }

    recorded_date = row.get("START", "")
    if recorded_date:
        resource["recordedDate"] = recorded_date

    return resource