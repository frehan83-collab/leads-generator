"""Vendor profile learning — update profiles after each extraction."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models.vendor_profile import VendorProfile

logger = logging.getLogger(__name__)


def _email_domain(email: Optional[str]) -> Optional[str]:
    if email and "@" in email:
        return email.split("@", 1)[1].lower()
    return None


def get_or_create_profile(
    db: Session,
    vendor_name: str,
    vendor_email: Optional[str] = None,
) -> VendorProfile:
    """Return existing profile or create a new one."""
    domain = _email_domain(vendor_email)

    profile = None
    if domain:
        profile = db.query(VendorProfile).filter_by(email_domain=domain).first()
    if not profile:
        profile = db.query(VendorProfile).filter_by(vendor_name=vendor_name).first()
    if not profile:
        profile = VendorProfile(
            vendor_name=vendor_name,
            email_domain=domain,
            vendor_email=vendor_email,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


def update_profile_after_extraction(
    db: Session,
    profile: VendorProfile,
    extraction: dict,
    confidence: float,
) -> None:
    """Update running averages and typical values after a successful extraction."""
    from datetime import datetime

    n = profile.invoice_count
    profile.avg_confidence = (profile.avg_confidence * n + confidence) / (n + 1)
    profile.invoice_count = n + 1
    profile.last_invoice_at = datetime.utcnow()

    if extraction.get("currency"):
        profile.typical_currency = extraction["currency"]
    if extraction.get("tax_rate"):
        profile.typical_tax_rate = extraction["tax_rate"]
    if extraction.get("payment_terms"):
        profile.typical_payment_terms = extraction["payment_terms"]
    if extraction.get("bank_details"):
        profile.bank_details = extraction["bank_details"]

    db.commit()
    logger.debug("Updated vendor profile for %s (invoice #%d)", profile.vendor_name, profile.invoice_count)


def apply_layout_hints(
    db: Session,
    profile: VendorProfile,
    hints: dict,
) -> None:
    """Store Claude-generated layout hints after human correction."""
    profile.layout_hints = hints.get("layout_hints", hints)
    db.commit()
    logger.info("Stored layout hints for vendor %s", profile.vendor_name)
