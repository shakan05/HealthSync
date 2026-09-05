"""
Main end-to-end pipeline execution script.
Orchestrates:
  1. Person 1: Ingestion & Validation (Source A & Source B)
  2. Person 2: FHIR Standardization & Mapping
  3. Prepares output bundles ready for Person 3 (Hashing & Storage)
"""

import json
from pathlib import Path

# Person 1 Imports
from adapters.source_a_synthea import run_source_a
from adapters.source_b_patient_records100k import run_source_b
from rejected import RejectedRecordWriter

# Person 2 Imports
from mappers.patient import map_patient
from mappers.encounter import map_encounter
from mappers.medication_request import map_medication_request
from mappers.condition import map_condition
from mappers.observation import map_observation
from mappers.procedure import map_procedure
from mappers.allergy import map_allergy

BASE_DIR = Path(__file__).resolve().parent

def run_pipeline():
    print("=== Starting HealthSync End-to-End Pipeline ===\n")
    
    # 1. Person 1: Ingestion & Validation
    rejected_writer = RejectedRecordWriter(str(BASE_DIR / "output" / "rejected_records.csv"))

    print("Running Person 1 validation & ingestion (Source A - Synthea)...")
    valid_a = run_source_a(str(BASE_DIR / "data" / "source_a"), rejected_writer)

    print("Running Person 1 validation & ingestion (Source B - 100K Records)...")
    valid_b = run_source_b(str(BASE_DIR / "data" / "source_b"), rejected_writer)

    rejected_writer.flush()
    print(f"-> Ingestion complete. Rejected records written to: {rejected_writer.output_path}\n")

    # 2. Person 2: FHIR Standardization & Mapping
    print("Running Person 2 FHIR standardization...")
    
    fhir_resources = []

    # Process Source A
    source_a_data = valid_a.get("source_a", valid_a) # fallback based on adapter structure
    # Loop and map Source A entities (Patients, Encounters, etc.)
    # Note: Adjust keys depending on your exact adapter return structure (e.g., 'patients', 'conditions')
    
    # Example structure processing layout:
    for patient_row in valid_a.get("patients", []):
        fhir_resources.append(map_patient(patient_row, "source_a"))
        
    for encounter_row in valid_a.get("encounters", []):
        fhir_resources.append(map_encounter(encounter_row, "source_a"))
        
    for condition_row in valid_a.get("conditions", []):
        fhir_resources.append(map_condition(condition_row, "source_a"))
        
    for observation_row in valid_a.get("observations", []):
        fhir_resources.append(map_observation(observation_row, "source_a"))
        
    for med_row in valid_a.get("medications", []):
        fhir_resources.append(map_medication_request(med_row, "source_a"))
        
    for proc_row in valid_a.get("procedures", []):
        fhir_resources.append(map_procedure(proc_row, "source_a"))
        
    for allergy_row in valid_a.get("allergies", []):
        fhir_resources.append(map_allergy(allergy_row, "source_a"))

    # Process Source B
    for patient_row in valid_b.get("patients", []):
        fhir_resources.append(map_patient(patient_row, "source_b"))
        
    for encounter_row in valid_b.get("encounters", []):
        fhir_resources.append(map_encounter(encounter_row, "source_b"))
        
    for condition_row in valid_b.get("conditions", []):
        fhir_resources.append(map_condition(condition_row, "source_b"))
        
    for observation_row in valid_b.get("observations", []):
        fhir_resources.append(map_observation(observation_row, "source_b"))
        
    for med_row in valid_b.get("medications", []):
        fhir_resources.append(map_medication_request(med_row, "source_b"))

    print(f"-> Successfully generated {len(fhir_resources)} standard FHIR resources.")
    print("\n=== Pipeline Execution Complete (Ready for Person 3) ===")
    
    return fhir_resources

if __name__ == "__main__":
    run_pipeline()