"""
Takes one FHIR resource (from a Person 2 map_*() function) plus the original
normalized row it came from, and:

  3b. Rewrites the resource's subject.reference from the raw provider patient
      id to your canonical healthsync_patient_id, using patient_id_mapping.
      This is what makes every resource for the same real patient queryable
      under one shared patient_id -- the actual mechanism behind the
      "unified longitudinal history" feature.

  3c. Generates a stable resource_id (natural id for encounters, since
      ENCOUNTER_ID already exists and other resources already reference
      encounters using that exact string; a hash of dup_key_fields for
      everything else, so re-running ingestion never creates duplicates)
      and inserts the resource into standardized_records + provenance.
"""

import hashlib
import json
import re

from identity import get_canonical_patient_id


_SUBJECT_REF_PATTERN = re.compile(r"^Patient/(?P<source>[^-]+)-(?P<raw_id>.+)$")

# Which fields identify a "distinct event" for resource types that don't
# have one natural id of their own. Mirrors schema.py's dup_key_fields.
DUP_KEY_FIELDS = {
    "conditions": ["PATIENT", "ENCOUNTER", "CODE", "START"],
    "medications": ["PATIENT", "ENCOUNTER", "CODE", "START", "STOP"],
    "observations": ["PATIENT", "ENCOUNTER", "CODE", "DATE"],
    "procedures": ["PATIENT", "ENCOUNTER", "CODE", "START"],
    "allergies": ["PATIENT", "ENCOUNTER", "CODE"],
}


def _resolve_subject_reference(cur, resource: dict) -> str:
    """
    3b. Parses resource['subject']['reference'] (format 'Patient/{source}-{raw_id}'),
    looks up the canonical healthsync_patient_id, and rewrites the reference
    in place to point at it. Returns the canonical id.
    """
    ref = resource.get("subject", {}).get("reference", "")
    match = _SUBJECT_REF_PATTERN.match(ref)
    if not match:
        raise ValueError(f"Unrecognized subject reference format: {ref!r}")

    source = match.group("source")
    raw_patient_id = match.group("raw_id")

    canonical_id = get_canonical_patient_id(cur, source, raw_patient_id)
    resource["subject"]["reference"] = f"Patient/{canonical_id}"
    return canonical_id


def _generate_resource_id(row: dict, resource_type: str, source: str) -> str:
    """
    3c (id part). Encounters use their own natural id (matches what other
    resources already reference them by, so no rewriting is ever needed for
    encounter links). Everything else gets a stable hash of its dup-key
    fields, so the same source row always produces the same resource_id.
    """
    if resource_type == "encounters":
        return f"{source}-{row.get('ENCOUNTER_ID', '')}"

    dup_key_fields = DUP_KEY_FIELDS.get(resource_type)
    if dup_key_fields is None:
        raise ValueError(f"No dup_key_fields defined for resource_type={resource_type!r}")

    key_parts = [str(row.get(field, "")) for field in dup_key_fields]
    key_string = "|".join(key_parts)
    digest = hashlib.sha256(key_string.encode()).hexdigest()[:16]
    return f"{source}-{digest}"


def write_standardized_record(cur, resource: dict, row: dict, resource_type: str,
                                source: str, event_date: str = None) -> str:
    """
    3b + 3c combined. Call this once per FHIR resource, right after mapping
    it, while `row` (the pre-FHIR normalized dict) is still in scope.

    resource: the FHIR dict returned by e.g. map_condition(row, source)
    row: the original normalized row that was passed into that mapper
    resource_type: "conditions", "encounters", "observations", etc.
        (matches schema.py's resource_type keys, NOT resource["resourceType"])
    source: "source_a" or "source_b"
    event_date: optional date string for the event_date column
        (e.g. row.get("START") or row.get("DATE"))

    Returns the resource_id that was stored.
    """
    canonical_patient_id = _resolve_subject_reference(cur, resource)
    resource_id = _generate_resource_id(row, resource_type, source)
    fhir_type = resource["resourceType"]

    cur.execute(
        """
        INSERT INTO standardized_records
            (patient_id, resource_type, resource_id, event_date, source_provider, resource_json)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (resource_type, resource_id) DO NOTHING
        RETURNING record_id
        """,
        (canonical_patient_id, fhir_type, resource_id, event_date, source, json.dumps(resource)),
    )
    result = cur.fetchone()

    if result is None:
        # Already existed (this exact row was ingested before) -- fetch its
        # record_id so provenance can still reference it if needed.
        cur.execute(
            "SELECT record_id FROM standardized_records WHERE resource_type = %s AND resource_id = %s",
            (fhir_type, resource_id),
        )
        result = cur.fetchone()

    record_id = result[0]

    cur.execute(
        """
        INSERT INTO provenance (record_id, source_provider, source_file, source_record_id)
        VALUES (%s, %s, %s, %s)
        """,
        (record_id, source, None, resource_id),
    )

    return resource_id
