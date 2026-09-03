"""
Entry point for Person 1's ingestion & validation layer.

Run with:  python3 main.py   (from any directory — paths below are resolved
relative to this file's location, not the current working directory)
"""

from pathlib import Path

from adapters.source_a_synthea import run_source_a
from adapters.source_b_patient_records100k import run_source_b
from rejected import RejectedRecordWriter

BASE_DIR = Path(__file__).resolve().parent


def main():
    rejected_writer = RejectedRecordWriter(str(BASE_DIR / "output" / "rejected_records.csv"))

    print("=== Running Source A (Synthea) ===")
    valid_a = run_source_a(str(BASE_DIR / "data" / "source_a"), rejected_writer)

    print("\n=== Running Source B (Patient Records 100K) ===")
    valid_b = run_source_b(str(BASE_DIR / "data" / "source_b"), rejected_writer)

    rejected_writer.flush()

    total_valid = sum(len(v) for v in valid_a.values()) + sum(len(v) for v in valid_b.values())
    print(f"\nTotal valid records (both sources): {total_valid}")
    print(f"Total rejected records: {rejected_writer.count()}")
    print(f"Rejected records written to: {rejected_writer.output_path}")

    return valid_a, valid_b


if __name__ == "__main__":
    main()
