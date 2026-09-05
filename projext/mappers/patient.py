"""
FHIR Patient resource mapper.

Maps Person 1's validated, normalized "patients" records (schema.py)
into FHIR Patient JSON, for both Source A (Synthea) and Source B
(Patient Records 100K).

Design decisions:
1. Namespaced IDs: resource ids are prefixed with the source name 
   (e.g., source_a-<id>, source_b-<id>) to prevent database collisions.
2. Source A carries rich demographics (first/last name, address, SSN, race/ethnicity),
   which are mapped fully.
3. Source B carries basic demographics only (patient_id, sex, age-approximated DOB),
   mapped honestly without fabricating missing fields.
4. Approximated DOB: Source B's derived birthdate is flagged with an extension
   so downstream components know it's an estimate.
"""

from typing import Optional


SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
APPROXIMATED_BIRTHDATE_EXTENSION = "http://healthsync.org/fhir/StructureDefinition/birthdate-approximated"


def _map_name(row: dict, source: str) -> list:
    if source == "source_a":
        given = [p for p in [row.get("FIRST"), row.get("MIDDLE")] if p]
        family = row.get("LAST", "")
        name = {}
        if given:
            name["given"] = given
        if family:
            name["family"] = family
        if name:
            name["use"] = "official"
            return [name]
    elif source == "source_b":
        # Source B has no name fields, just patient_id
        return [{"use": "official", "text": f"Patient {row.get('PATIENT_ID', '')}"}]
    return []


def _map_gender(sex: str) -> Optional[str]:
    # FHIR administrative-gender values: male, female, other, unknown
    sex_upper = sex.upper()
    if sex_upper == "M":
        return "male"
    if sex_upper == "F":
        return "female"
    return None


def _map_identifiers(row: dict, source: str) -> list:
    identifiers = []
    
    # Source A has a native SSN field
    if source == "source_a" and row.get("SSN"):
        identifiers.append({
            "system": SSN_SYSTEM,
            "value": row["SSN"]
        })
        
    return identifiers


def _map_extensions(row: dict, source: str) -> list:
    extensions = []
    
    # If Source B approximated the birthdate from age, flag it
    if source == "source_b" and row.get("_birthdate_is_approximated") == "true":
        extensions.append({
            "url": APPROXIMATED_BIRTHDATE_EXTENSION,
            "valueBoolean": True
        })
        
    return extensions


def map_patient(row: dict, source: str) -> dict:
    """
    row: a single normalized "patients" record as produced by either
         source_a_synthea.py or source_b_patient_records100k.py
    source: "source_a" or "source_b"

    Returns a FHIR Patient resource dict.
    """
    if source not in ("source_a", "source_b"):
        raise ValueError(f"unknown source '{source}' -- must be 'source_a' or 'source_b'")

    patient_id = row.get("PATIENT_ID", "")

    resource = {
        "resourceType": "Patient",
        "active": True,
    }

    name = _map_name(row, source)
    if name:
        resource["name"] = name

    gender = _map_gender(row.get("GENDER", ""))
    if gender:
        resource["gender"] = gender

    birthdate = row.get("BIRTHDATE", "")
    if birthdate:
        resource["birthDate"] = birthdate

    deathdate = row.get("DEATHDATE", "")
    if deathdate:
        resource["deceasedDateTime"] = deathdate

    identifiers = _map_identifiers(row, source)
    if identifiers:
        resource["identifier"] = identifiers

    extensions = _map_extensions(row, source)
    if extensions:
        resource["extension"] = extensions

    return resource