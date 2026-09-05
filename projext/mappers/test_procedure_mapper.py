import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from mappers.procedure import map_procedure

# Source A (Synthea Procedure - SNOMED)
source_a_procedure = {
    "PATIENT": "abc-123-def",
    "ENCOUNTER": "enc-789",
    "DATE": "2023-05-19T14:00:00Z",
    "CODE": "80146002",
    "DESCRIPTION": "Appendectomy",
}

print("=== Source A Procedure (Synthea Appendectomy) ===")
print(json.dumps(map_procedure(source_a_procedure, "source_a"), indent=2))