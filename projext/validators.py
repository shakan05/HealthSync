"""
The shared validate_row() pipeline both adapters feed into.

Five stages, run in order, short-circuiting on first failure per row
(so a row that fails structurally doesn't also get flagged for a dozen
downstream reasons — one clear rejection reason per row):

  1. Structural   - dates parseable (columns/shape are guaranteed by the time
                     a row reaches here, since the adapter reads via known headers)
  2. Required      - required fields present and non-empty
  3. Value         - per-resource-type format/range/allowed-value checks
  4. Reference     - referenced patient/encounter actually exists
  5. Duplicate     - same natural key not already seen in this load
"""

from datetime import datetime
from typing import Optional

from schema import ResourceConfig


class ValidationContext:
    """Tracks identity sets (for reference checks) and dup keys across a load run."""

    def __init__(self):
        # resource_type -> set of identity values seen so far (e.g. patients -> {PATIENT_ID,...})
        self.identity_sets: dict[str, set[str]] = {}
        # resource_type -> set of dup keys (tuples) seen so far
        self.dup_keys: dict[str, set[tuple]] = {}

    def register_identity(self, resource_type: str, value: str) -> None:
        self.identity_sets.setdefault(resource_type, set()).add(value)

    def has_identity(self, resource_type: str, value: str) -> bool:
        return value in self.identity_sets.get(resource_type, set())

    def is_duplicate(self, resource_type: str, key: tuple) -> bool:
        seen = self.dup_keys.setdefault(resource_type, set())
        if key in seen:
            return True
        seen.add(key)
        return False


def _parse_date(value: str) -> bool:
    if not value:
        return True  # emptiness is a required-field concern, not a structural one
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def _parse_numeric(value: str) -> bool:
    if not value:
        return True
    try:
        float(value)
        return True
    except ValueError:
        return False


def validate_row(
    row: dict,
    config: ResourceConfig,
    ctx: ValidationContext,
) -> tuple[bool, Optional[str]]:
    """
    Returns (is_valid, reason). reason is None when is_valid is True.
    """

    # --- 1. Structural: dates parseable ---
    for date_field in config.date_fields:
        val = row.get(date_field, "")
        if not _parse_date(val):
            return False, f"structural: {date_field}='{val}' is not a parseable date"

    for num_field in config.numeric_fields:
        val = row.get(num_field, "")
        if not _parse_numeric(val):
            return False, f"structural: {num_field}='{val}' is not numeric"

    # --- 2. Required fields ---
    for req_field in config.required_fields:
        val = row.get(req_field, "")
        if val is None or str(val).strip() == "":
            return False, f"required: '{req_field}' is missing or empty"

    # --- 3. Value validation (per-field custom rules) ---
    for field_name, rule in config.value_rules.items():
        val = row.get(field_name, "")
        error = rule(val, row)
        if error:
            return False, f"value: {error}"

    # --- 4. Reference validation ---
    for field_name, referenced_resource in config.reference_fields:
        val = row.get(field_name, "")
        if val and not ctx.has_identity(referenced_resource, val):
            return False, (
                f"reference: {field_name}='{val}' does not exist in "
                f"'{referenced_resource}' (loaded so far)"
            )

    # --- 5. Duplicate detection ---
    dup_key = tuple(row.get(f, "") for f in config.dup_key_fields)
    if ctx.is_duplicate(config.resource_type, dup_key):
        return False, f"duplicate: key {dup_key} already loaded for {config.resource_type}"

    # --- Register identity for downstream reference checks ---
    if config.identity_field:
        ctx.register_identity(config.resource_type, row.get(config.identity_field, ""))

    return True, None
