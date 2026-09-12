-- HealthSync AI — Person 3: Patient Identity Resolution + Storage
-- PostgreSQL schema for standardized_records, patient identity, and provenance.

-- Single sequence for human-readable patient IDs (HS-P00001, HS-P00002, ...),
-- shared across both sources. Which source a patient came from is tracked in
-- patient_id_mapping.source_provider / provenance.source_provider, not in the ID itself.
CREATE SEQUENCE healthsync_patient_seq START 1;

CREATE TABLE patients (
    healthsync_patient_id TEXT PRIMARY KEY,
    name TEXT,
    date_of_birth DATE,
    gender TEXT,
    ssn TEXT UNIQUE
);

CREATE TABLE patient_id_mapping (
    healthsync_patient_id TEXT REFERENCES patients(healthsync_patient_id),
    source_provider TEXT,
    provider_patient_id TEXT,
    PRIMARY KEY (source_provider, provider_patient_id)
);

CREATE TABLE standardized_records (
    record_id SERIAL PRIMARY KEY,
    patient_id TEXT REFERENCES patients(healthsync_patient_id),
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    event_date DATE,
    source_provider TEXT,
    resource_json JSONB NOT NULL,
    UNIQUE (resource_type, resource_id)
);

CREATE TABLE provenance (
    record_id INTEGER REFERENCES standardized_records(record_id),
    source_provider TEXT,
    source_file TEXT,
    source_record_id TEXT,
    ingested_at TIMESTAMP DEFAULT now()
);

CREATE TABLE rejected_records (
    id SERIAL PRIMARY KEY,
    source TEXT,
    resource_type TEXT,
    row_number INTEGER,
    reason TEXT,
    raw_row JSONB
);
