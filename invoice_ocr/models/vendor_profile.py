"""Vendor profile model for supplier learning."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text
from .base import Base


class VendorProfile(Base):
    __tablename__ = "vendor_profiles"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Identification
    vendor_name = Column(String(255), nullable=False, index=True)
    email_domain = Column(String(100), nullable=True, index=True)
    vendor_email = Column(String(255), nullable=True)

    # Layout hints stored as JSON (field positions, typical formats, etc.)
    layout_hints = Column(JSON, nullable=True)

    # Accuracy tracking
    invoice_count = Column(Integer, default=0)
    avg_confidence = Column(Float, default=0.0)
    last_invoice_at = Column(DateTime, nullable=True)

    # Typical values for validation
    typical_currency = Column(String(10), nullable=True)
    typical_tax_rate = Column(Float, nullable=True)
    typical_payment_terms = Column(String(255), nullable=True)
    bank_details = Column(JSON, nullable=True)

    # Notes about this vendor's invoices
    notes = Column(Text, nullable=True)

    def to_context_string(self) -> str:
        """Return a human-readable summary to inject into Claude's prompt."""
        lines = [f"Vendor: {self.vendor_name}"]
        if self.typical_currency:
            lines.append(f"Typical currency: {self.typical_currency}")
        if self.typical_tax_rate:
            lines.append(f"Typical tax rate: {self.typical_tax_rate}%")
        if self.typical_payment_terms:
            lines.append(f"Typical payment terms: {self.typical_payment_terms}")
        if self.layout_hints:
            lines.append(f"Layout hints: {self.layout_hints}")
        lines.append(f"Previously processed {self.invoice_count} invoices, avg confidence {self.avg_confidence:.2f}")
        return "\n".join(lines)
