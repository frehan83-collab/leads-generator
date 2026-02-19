"""Invoice and line-item SQLAlchemy models."""

import enum
import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text,
    Enum, ForeignKey, Boolean, JSON,
)
from sqlalchemy.orm import relationship

from .base import Base


class InvoiceStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # File info
    original_filename = Column(String(255))
    file_path = Column(String(512))
    file_format = Column(String(20))  # pdf, jpg, png, xml, csv, edi

    # Status & processing
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.PENDING)
    processing_error = Column(Text, nullable=True)
    ocr_text = Column(Text, nullable=True)

    # Extracted fields
    vendor_name = Column(String(255), nullable=True)
    vendor_address = Column(Text, nullable=True)
    vendor_email = Column(String(255), nullable=True)
    vendor_phone = Column(String(50), nullable=True)

    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(String(20), nullable=True)   # stored as YYYY-MM-DD string
    due_date = Column(String(20), nullable=True)

    currency = Column(String(10), nullable=True)
    subtotal = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    tax_rate = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)

    po_number = Column(String(100), nullable=True)
    payment_terms = Column(String(255), nullable=True)
    bank_details = Column(JSON, nullable=True)

    # AI quality
    confidence_score = Column(Float, nullable=True)
    extraction_notes = Column(Text, nullable=True)
    validation_errors = Column(JSON, nullable=True)

    # Duplicate detection
    content_hash = Column(String(64), nullable=True, index=True)

    # Approval workflow
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    erp_post_result = Column(JSON, nullable=True)

    # Relationships
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="invoice", cascade="all, delete-orphan")

    def compute_hash(self) -> str:
        """Hash invoice_number + vendor_name + total_amount for duplicate detection."""
        raw = f"{self.invoice_number}|{self.vendor_name}|{self.total_amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "vendor_name": self.vendor_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "due_date": self.due_date,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "tax_rate": self.tax_rate,
            "total_amount": self.total_amount,
            "po_number": self.po_number,
            "payment_terms": self.payment_terms,
            "bank_details": self.bank_details,
            "vendor_email": self.vendor_email,
            "vendor_phone": self.vendor_phone,
            "vendor_address": self.vendor_address,
            "confidence_score": self.confidence_score,
            "extraction_notes": self.extraction_notes,
            "validation_errors": self.validation_errors,
            "line_items": [li.to_dict() for li in self.line_items],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    description = Column(Text, nullable=True)
    quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    line_total = Column(Float, nullable=True)
    gl_account = Column(String(50), nullable=True)
    tax_code = Column(String(20), nullable=True)

    invoice = relationship("Invoice", back_populates="line_items")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "line_total": self.line_total,
            "gl_account": self.gl_account,
            "tax_code": self.tax_code,
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    action = Column(String(100))
    user = Column(String(100), nullable=True)
    details = Column(JSON, nullable=True)

    invoice = relationship("Invoice", back_populates="audit_logs")
