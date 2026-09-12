"""
Patient identity resolution.

Source A (Synthea): resolved via exact SSN match. Same real-world person
across multiple Synthea files/patients rows -> same healthsync_patient_id.
(Source B was originally supported here too, but the team decided not to
use Source B at all -- see project notes -- so that path has been removed.)
"""

import re

try:
    from .db import get_connection  # when imported as part of the storage package
except ImportError:
    from db import get_connection  # when run standalone (e.g. python identity.py)


def _next_id(cur) -> str:
    """Pulls the next number from the shared patient sequence and formats it
    as e.g. HS-P00001. Using a real DB sequence (not a Python counter) means
    concurrent inserts can never produce a duplicate ID. Both sources share
    one sequence and one prefix -- which source a patient came from is
    tracked in patient_id_mapping.source_provider, not in the ID itself."""
    cur.execute("SELECT nextval('healthsync_patient_seq')")
    number = cur.fetchone()[0]
    return f"HS-P{number:05d}"


def normalize_ssn(raw_ssn: str) -> str | None:
    """Strip formatting, keep only digits. Returns None if invalid shape."""
    if not raw_ssn:
        return None
    digits = re.sub(r"\D", "", raw_ssn)
    if len(digits) != 9:
        return None
    return digits


def _lookup_patient_by_ssn(cur, ssn: str) -> str | None:
    cur.execute("SELECT healthsync_patient_id FROM patients WHERE ssn = %s", (ssn,))
    row = cur.fetchone()
    return row[0] if row else None


def _insert_patient(cur, healthsync_id: str, ssn: str | None, name: str = None,
                     date_of_birth: str = None, gender: str = None) -> None:
    cur.execute(
        """
        INSERT INTO patients (healthsync_patient_id, name, date_of_birth, gender, ssn)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (healthsync_id, name, date_of_birth, gender, ssn),
    )


def _insert_patient_id_mapping(cur, healthsync_id: str, source_provider: str,
                                provider_patient_id: str) -> None:
    cur.execute(
        """
        INSERT INTO patient_id_mapping (healthsync_patient_id, source_provider, provider_patient_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (source_provider, provider_patient_id) DO NOTHING
        """,
        (healthsync_id, source_provider, provider_patient_id),
    )


def resolve_patient_identity(cur, source_provider: str, provider_patient_id: str,
                              raw_ssn: str, name: str = None,
                              date_of_birth: str = None, gender: str = None) -> str:
    """
    Source A path. Returns a healthsync_patient_id, reusing an existing one
    if this SSN has been seen before, creating a new one otherwise. Raises
    ValueError if the SSN is missing/malformed (this row should have been
    rejected earlier by schema.py validation, so this is a safety net).
    """
    ssn = normalize_ssn(raw_ssn)
    if ssn is None:
        raise ValueError(f"Invalid/missing SSN for {source_provider}/{provider_patient_id}")

    existing = _lookup_patient_by_ssn(cur, ssn)
    if existing:
        healthsync_id = existing
    else:
        healthsync_id = _next_id(cur)
        _insert_patient(cur, healthsync_id, ssn, name, date_of_birth, gender)

    _insert_patient_id_mapping(cur, healthsync_id, source_provider, provider_patient_id)
    return healthsync_id


def get_canonical_patient_id(cur, source_provider: str, provider_patient_id: str) -> str:
    """
    Used by every non-patient resource type (encounters, conditions, ...) to
    translate a provider-local patient reference into the canonical ID.
    Raises ValueError if no mapping exists -- this should never happen if
    patients.csv was processed first, per LOAD_ORDER.
    """
    cur.execute(
        "SELECT healthsync_patient_id FROM patient_id_mapping "
        "WHERE source_provider = %s AND provider_patient_id = %s",
        (source_provider, provider_patient_id),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(
            f"No patient mapping found for {source_provider}/{provider_patient_id} "
            f"-- was patients.csv processed first?"
        )
    return row[0]


if __name__ == "__main__":
    # Quick manual test against a made-up row. Replace with real Synthea
    # patients.csv rows once you're ready to test for real.
    conn = get_connection()
    cur = conn.cursor()

    id1 = resolve_patient_identity(cur, "source_a", "synthea-uuid-1", "123-45-6789")
    id2 = resolve_patient_identity(cur, "source_a", "synthea-uuid-1", "123-45-6789")
    print(f"Same patient re-ingested: {id1} == {id2} -> {id1 == id2}")

    conn.rollback()  # don't actually persist this test run
    cur.close()
    conn.close()
