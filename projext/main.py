
from pathlib import Path

from adapters.source_a_synthea import run_source_a
from rejected import RejectedRecordWriter

BASE_DIR = Path(__file__).resolve().parent


def main():
    rejected_writer = RejectedRecordWriter(str(BASE_DIR / "output" / "rejected_records.csv"))

    print("=== Running Source A (Synthea) ===")
    valid_records = run_source_a(str(BASE_DIR / "data" / "source_a"), rejected_writer)

    rejected_writer.flush()

    total_valid = sum(len(v) for v in valid_records.values())
    print(f"\nTotal valid records: {total_valid}")
    print(f"Total rejected records: {rejected_writer.count()}")
    print(f"Rejected records written to: {rejected_writer.output_path}")

    return valid_records


if __name__ == "__main__":
    main()