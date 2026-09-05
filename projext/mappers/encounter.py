"""
FHIR Encounter resource mapper.

Maps Person 1's validated, normalized "encounters" records (schema.py)
into FHIR Encounter JSON, for both Source A (Synthea) and Source B
(Patient Records 100K outcomes.csv).

Design decisions:
1. Class mapping (`encounterclass`): Source A provides explicit encounter
   classes (ambulatory, emergency, inpatient, wellness, etc.). Source B
   encounters are synthesized entirely from outcomes.csv, which represents
   hospitalizations, so they are explicitly typed as "inpatient".
2. Coding: Source A maps the encounter CODE to SNOMED or local encounter codes.
   Source B maps the primary_drg code with CODE_SYSTEM = "DRG".
3. Resource `id` is intentionally NOT assigned here (left for Person 3).
"""

from typing import Optional


SNOMED_ENCOUNTER_SYSTEM = "http://snomed.info/sct"
DRG_SYSTEM = "http://hl7.org/fhir/sid/drg"


def _patient_ref(source: str, patient_id: str) -> dict:
    return {"reference": f"Patient/{source}-{patient_id}"}


def _map_class(encounter_class: str) -> dict:
    """
    FHIR requires a class coding (typically from http://terminology.hl7.org/CodeSystem/v3-ActCode).
    We map the string representation into a valid coding structure.
    """
    code_lower = encounter_class.lower()
    # Common mappings to v3-ActCode
    v3_map = {
        "inpatient": ("IMP", "inpatient encounter"),
        "outpatient": ("AMB", "ambulatory"),
        "ambulatory": ("AMB", "ambulatory"),
        "emergency": ("EMER", "emergency"),
        "wellness": ("AMB", "ambulatory"),
        "virtual": ("VR", "virtual"),
    }
    
    code, display = v3_map.get(code_lower, ("AMB", encounter_class or "ambulatory"))
    return {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": code,
        "display": display,
    }


def _map_type_coding(row: dict, source: str) -> list:
    """
    Maps the encounter's primary code (e.g. SNOMED for Synthea, DRG for Source B).
    """
    code = row.get("CODE", "")
    description = row.get("DESCRIPTION", "")
    code_system = row.get("CODE_SYSTEM", "")

    if not code:
        return []

    system = DRG_SYSTEM if code_system == "DRG" else SNOMED_ENCOUNTER_SYSTEM

    coding = {"system": system, "code": code}
    if description:
        coding["display"] = description

    return [{"coding": [coding]}]


def map_encounter(row: dict, source: str) -> dict:
    """
    row: a single normalized "encounters" record as produced by either
         source_a_synthea.py or source_b_patient_records100k.py
    source: "source_a" or "source_b"

    Returns a FHIR Encounter resource dict.
    """
    if source not in ("source_a", "source_b"):
        raise ValueError(f"unknown source '{source}' -- must be 'source_a' or 'source_b'")

    # Infer status: if STOP is present, completed; otherwise active/in-progress
    status = "completed" if row.get("STOP") else "in-progress"

    resource = {
        "resourceType": "Encounter",
        "status": status,
        "class": _map_class(row.get("ENCOUNTERCLASS", "")),
        "subject": _patient_ref(source, row.get("PATIENT", "")),
    }

    type_coding = _map_type_coding(row, source)
    if type_coding:
        resource["type"] = type_coding

    period = {}
    if row.get("START"):
        period["start"] = row["START"]
    if row.get("STOP"):
        period["end"] = row["STOP"]
    if period:
        resource["period"] = period

    return resource