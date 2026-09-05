"""
FHIR Observation resource mapper.

Maps Person 1's validated, normalized "observations" records (schema.py)
into FHIR Observation JSON, for both Source A (Synthea) and Source B
(Patient Records 100K).

Design decisions:
1. Status: FHIR Observation `status` is required; defaulted to "final" since 
   these are completed clinical measurements/labs.
2. Coding systems: Source A uses LOINC codes for observations. Source B uses 
   standardized lab test names/codes handled by Person 1's adapter.
3. Value quantities: If a numeric value and unit are provided, they are mapped 
   into valueQuantity. If non-numeric or text-based, handled gracefully via 
   valueString or text display.
4. Resource id is intentionally left for Person 3.
"""

from typing import Optional


LOINC_SYSTEM = "http://loinc.org"


def _patient_ref(source: str, patient_id: str) -> dict:
    return {"reference": f"Patient/{source}-{patient_id}"}


def _encounter_ref(source: str, encounter_id: str) -> Optional[dict]:
    if not encounter_id:
        return None
    return {"reference": f"Encounter/{source}-{encounter_id}"}


def _map_observation_coding(row: dict) -> dict:
    code = row.get("CODE", "")
    description = row.get("DESCRIPTION", "")

    coding = {"system": LOINC_SYSTEM, "code": code}
    if description:
        coding["display"] = description

    concept = {"coding": [coding]}
    if description:
        concept["text"] = description
    return concept


def _map_value(row: dict) -> dict:
    """
    Maps value and units if numeric, otherwise falls back or omits safely.
    """
    value = row.get("VALUE", "")
    units = row.get("UNITS", "")

    if not value:
        return {}

    try:
        # Try casting to float for standard FHIR quantity
        numeric_value = float(value)
        quantity = {"value": numeric_value}
        if units:
            quantity["unit"] = units
        return {"valueQuantity": quantity}
    except ValueError:
        # Non-numeric value (e.g., text-based result)
        return {"valueString": str(value)}


def map_observation(row: dict, source: str) -> dict:
    """
    row: a single normalized "observations" record from either source.
    source: "source_a" or "source_b"

    Returns a FHIR Observation resource dict.
    """
    if source not in ("source_a", "source_b"):
        raise ValueError(f"unknown source '{source}' -- must be 'source_a' or 'source_b'")

    resource = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
                "display": "Laboratory"
            }]
        }],
        "code": _map_observation_coding(row),
        "subject": _patient_ref(source, row.get("PATIENT", "")),
    }

    encounter_ref = _encounter_ref(source, row.get("ENCOUNTER", ""))
    if encounter_ref:
        resource["encounter"] = encounter_ref

    effective_date = row.get("DATE", "") or row.get("START", "")
    if effective_date:
        resource["effectiveDateTime"] = effective_date

    value_dict = _map_value(row)
    if value_dict:
        resource.update(value_dict)

    return resource
