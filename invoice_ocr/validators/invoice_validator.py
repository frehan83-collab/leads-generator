"""Math validation, duplicate detection, and confidence checks."""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from ..models.invoice import Invoice

logger = logging.getLogger(__name__)
TOLERANCE = 0.02  # 2 cents tolerance for float rounding


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_duplicate: bool = False
    needs_review: bool = False


def validate_invoice(extraction: dict, db: Session, existing_invoice_id: Optional[int] = None) -> ValidationResult:
    """Run all validation checks on extracted invoice data."""
    errors = []
    warnings = []

    # --- Math validation ---
    line_items = extraction.get("line_items") or []
    subtotal = extraction.get("subtotal")
    tax_amount = extraction.get("tax_amount")
    total_amount = extraction.get("total_amount")

    if line_items and subtotal is not None:
        computed_subtotal = sum(
            (item.get("line_total") or 0) for item in line_items
        )
        if abs(computed_subtotal - subtotal) > TOLERANCE:
            errors.append(
                f"Line items sum ({computed_subtotal:.2f}) does not match subtotal ({subtotal:.2f})"
            )

    if subtotal is not None and tax_amount is not None and total_amount is not None:
        computed_total = subtotal + tax_amount
        if abs(computed_total - total_amount) > TOLERANCE:
            errors.append(
                f"subtotal + tax ({computed_total:.2f}) does not match total ({total_amount:.2f})"
            )

    # --- Required fields check ---
    for required in ("vendor_name", "invoice_number", "total_amount"):
        if not extraction.get(required):
            warnings.append(f"Missing recommended field: {required}")

    # --- Date format check ---
    for date_field in ("invoice_date", "due_date"):
        val = extraction.get(date_field)
        if val and not _is_valid_date(val):
            warnings.append(f"{date_field} is not in YYYY-MM-DD format: {val}")

    # --- Confidence check ---
    confidence = extraction.get("confidence_score", 0.0)
    needs_review = confidence < 0.85

    # --- Duplicate detection ---
    is_duplicate = False
    invoice_number = extraction.get("invoice_number")
    vendor_name = extraction.get("vendor_name")
    if invoice_number and vendor_name and total_amount:
        raw = f"{invoice_number}|{vendor_name}|{total_amount}"
        content_hash = hashlib.sha256(raw.encode()).hexdigest()
        query = db.query(Invoice).filter_by(content_hash=content_hash)
        if existing_invoice_id:
            query = query.filter(Invoice.id != existing_invoice_id)
        if query.first():
            is_duplicate = True
            errors.append(f"Duplicate invoice detected: {invoice_number} from {vendor_name}")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        is_duplicate=is_duplicate,
        needs_review=needs_review,
    )


def _is_valid_date(date_str: str) -> bool:
    """Check YYYY-MM-DD format."""
    import re
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", date_str))
