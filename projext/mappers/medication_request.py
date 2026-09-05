"""
FHIR MedicationRequest resource mapper.

Priority resource per the task doc: whoever builds cross-source
contradiction detection depends on this mapping directly, so get it right.

Maps Person 1's validated, normalized "medications" records (schema.py)
into FHIR MedicationRequest JSON, for both Source A (Synthea) and Source B
(Patient Records 100K).

Design decisions made explicit here (not silently assumed):

1. FHIR `status` is a required field, but neither source has an explicit
   status column. Inferred: STOP present -> "completed", STOP absent ->
   "active". This is a disclosed domain inference, not a fabricated fact --
   flagged in code and in resource_json terms, not hidden.

2. `intent` is set to "order" for every row. Neither source distinguishes
   order/plan/proposal, and "order" is the correct default for a completed
   or active prescription event coming from clinical/claims data.

3. `medicationCodeableConcept.coding` system differs by source:
   - Source A: CODE is a real RxNorm code (Synthea generates RxNorm-coded
     medications) -> tagged with the standard RxNorm system URI.
   - Source B: CODE is a raw drug name (CODE_SYSTEM == "drug_name_uncoded",
     set by Person 1's adapter) -> tagged with a clearly non-standard
     placeholder system URI so nothing downstream treats it as a real code.

4. No structured dose/frequency is extracted from Source A's free-text
   DESCRIPTION field (e.g. "10 ML metFORMIN hydrochloride 500 MG/ML
   Injection"). Parsing dose out of that text is an NLP task -- arguably
   Person 4's (Clinical NER) territory, not something to regex-guess here.
   Source B DOES have structured dose/unit/frequency as raw passthrough
   fields (not part of the shared schema, but present on the row dict per
   source_b_patient_records100k.py's _normalize_medications()), so those
   are used directly for Source B's dosageInstruction.

5. Resource `id` is intentionally NOT assigned here. Per the task doc,
   resource_id generation is Person 3's job (identity resolution + storage,
   using a deterministic hash). Assigning our own id here would create two
   competing id schemes.
"""

from typing import Optional


RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
UNCODED_DRUG_NAME_SYSTEM = "urn:healthsync:uncoded:drug_name"


def _patient_ref(source: str, patient_id: str) -> dict:
    return {"reference": f"Patient/{source}-{patient_id}"}


def _encounter_ref(source: str, encounter_id: str) -> Optional[dict]:
    if not encounter_id:
        return None
    return {"reference": f"Encounter/{source}-{encounter_id}"}


def _infer_status(stop: str) -> str:
    """
    Disclosed inference, not a fact from the source data: neither source
    has an explicit MedicationRequest status column. STOP present is taken
    to mean the course of medication ended (-> "completed"); STOP absent
    means it's still ongoing as far as the data shows (-> "active").
    """
    return "completed" if stop else "active"


def _map_medication_coding(row: dict) -> dict:
    """
    Returns the medicationCodeableConcept. System depends on source, per
    module docstring point 3. CODE_SYSTEM is set by Person 1's adapters --
    Source A rows don't set it (implicitly RxNorm, Synthea's native coding),
    Source B rows explicitly set CODE_SYSTEM = "drug_name_uncoded".
    """
    code = row.get("CODE", "")
    description = row.get("DESCRIPTION", "")
    code_system = row.get("CODE_SYSTEM", "")  # only set explicitly by Source B

    system = UNCODED_DRUG_NAME_SYSTEM if code_system == "drug_name_uncoded" else RXNORM_SYSTEM

    coding = {"system": system, "code": code}
    if description:
        coding["display"] = description

    concept = {"coding": [coding]}
    if description:
        concept["text"] = description
    return concept


def _map_dosage_instruction(row: dict, source: str) -> list:
    """
    Source B only -- see module docstring point 4. dose/unit/frequency are
    raw passthrough fields on Source B rows (not shared-schema fields), so
    they're only present when source == "source_b".
    """
    if source != "source_b":
        return []

    dose = row.get("dose", "")
    unit = row.get("unit", "")
    frequency = row.get("frequency", "")
    if not (dose or frequency):
        return []

    text_parts = [p for p in [f"{dose} {unit}".strip() if dose else "", frequency] if p]
    dosage = {"text": " ".join(text_parts)} if text_parts else {}

    if dose and unit:
        try:
            dosage["doseAndRate"] = [
                {"doseQuantity": {"value": float(dose), "unit": unit}}
            ]
        except ValueError:
            pass  # non-numeric dose -- keep the free-text version above, don't fabricate a quantity

    return [dosage] if dosage else []


def _map_dispense_request(row: dict, source: str) -> Optional[dict]:
    """
    Source A: DISPENSES (numeric refill count) -> numberOfRepeatsAllowed.
    Source B: duration_days (raw passthrough field) -> expectedSupplyDuration.
    """
    dispense_request = {}

    if source == "source_a" and row.get("DISPENSES"):
        try:
            dispense_request["numberOfRepeatsAllowed"] = int(float(row["DISPENSES"]))
        except ValueError:
            pass

    if source == "source_b" and row.get("duration_days"):
        try:
            dispense_request["expectedSupplyDuration"] = {
                "value": float(row["duration_days"]),
                "unit": "days",
            }
        except ValueError:
            pass

    validity_period = {}
    if row.get("START"):
        validity_period["start"] = row["START"]
    if row.get("STOP"):
        validity_period["end"] = row["STOP"]
    if validity_period:
        dispense_request["validityPeriod"] = validity_period

    return dispense_request or None


def _map_reason_code(row: dict, source: str) -> list:
    """
    Source A: REASONCODE/REASONDESCRIPTION (raw passthrough, coded).
    Source B: indication (raw passthrough, free text only, no code).
    """
    if source == "source_a" and row.get("REASONCODE"):
        coding = {"code": row["REASONCODE"]}
        if row.get("REASONDESCRIPTION"):
            coding["display"] = row["REASONDESCRIPTION"]
        return [{"coding": [coding]}]

    if source == "source_b" and row.get("indication"):
        return [{"text": row["indication"]}]

    return []


def map_medication_request(row: dict, source: str) -> dict:
    """
    row: a single normalized "medications" record as produced by either
         source_a_synthea.py or source_b_patient_records100k.py
    source: "source_a" or "source_b" -- required, see patient.py for why.

    Returns a FHIR MedicationRequest resource (dict, ready to json.dumps).
    No `id` is set -- see module docstring point 5.
    """
    if source not in ("source_a", "source_b"):
        raise ValueError(f"unknown source '{source}' -- must be 'source_a' or 'source_b'")

    resource = {
        "resourceType": "MedicationRequest",
        "status": _infer_status(row.get("STOP", "")),
        "intent": "order",
        "medicationCodeableConcept": _map_medication_coding(row),
        "subject": _patient_ref(source, row.get("PATIENT", "")),
    }

    encounter_ref = _encounter_ref(source, row.get("ENCOUNTER", ""))
    if encounter_ref:
        resource["encounter"] = encounter_ref

    if row.get("START"):
        resource["authoredOn"] = row["START"]

    dosage = _map_dosage_instruction(row, source)
    if dosage:
        resource["dosageInstruction"] = dosage

    dispense_request = _map_dispense_request(row, source)
    if dispense_request:
        resource["dispenseRequest"] = dispense_request

    reason_code = _map_reason_code(row, source)
    if reason_code:
        resource["reasonCode"] = reason_code

    return resource