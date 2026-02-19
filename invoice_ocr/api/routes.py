"""FastAPI route definitions for the invoice OCR API."""

import hashlib
import logging
import os
import shutil
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Query
from fastapi.responses import JSONResponse
from typing import List
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models.base import get_db
from ..models.invoice import Invoice, InvoiceLineItem, InvoiceStatus, AuditLog
from ..models.vendor_profile import VendorProfile
from ..validators import validate_invoice
from ..erp import active_connector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/invoices", tags=["invoices"])
stats_router = APIRouter(prefix="/api/stats", tags=["stats"])


# ─────────────────────────────────────── upload ────────────────────────────────

@router.post("/upload")
async def upload_invoices(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload one or more invoice files and queue them for processing."""
    _ensure_storage()
    results = []

    for file in files:
        dest = os.path.join(settings.storage_path, file.filename)
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        invoice = Invoice(
            original_filename=file.filename,
            file_path=dest,
            file_format=os.path.splitext(file.filename)[1].lstrip(".").lower(),
            status=InvoiceStatus.PENDING,
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)

        _log(db, invoice.id, "uploaded", details={"filename": file.filename})

        try:
            from ..workers.celery_tasks import process_invoice_task
            process_invoice_task.delay(invoice.id)
        except Exception as e:
            logger.warning("Celery unavailable (%s) — processing in-process", e)
            await _process_async(invoice.id)
            db.refresh(invoice)

        results.append({"invoice_id": invoice.id, "status": invoice.status, "filename": file.filename})

    return results


# ─────────────────────────────────────── get / list ────────────────────────────

@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = _get_or_404(db, invoice_id)
    return invoice.to_dict()


@router.get("/{invoice_id}/status")
def get_status(invoice_id: int, db: Session = Depends(get_db)):
    invoice = _get_or_404(db, invoice_id)
    return {
        "invoice_id": invoice.id,
        "status": invoice.status,
        "confidence_score": invoice.confidence_score,
        "validation_errors": invoice.validation_errors,
    }


@router.get("/")
def list_invoices(
    vendor: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Invoice)
    if vendor:
        q = q.filter(Invoice.vendor_name.ilike(f"%{vendor}%"))
    if status:
        q = q.filter(Invoice.status == status)
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_to)

    total = q.count()
    invoices = q.order_by(Invoice.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "invoices": [i.to_dict() for i in invoices],
    }


# ─────────────────────────────────────── corrections ───────────────────────────

@router.put("/{invoice_id}/correct")
async def correct_invoice(invoice_id: int, corrections: dict, db: Session = Depends(get_db)):
    """Human correction — updates DB and feeds back to vendor learning."""
    from ..ai.claude_client import ClaudeExtractionClient
    from ..ai.vendor_learning import get_or_create_profile, apply_layout_hints

    invoice = _get_or_404(db, invoice_id)
    original = invoice.to_dict()

    for key, val in corrections.items():
        if hasattr(invoice, key):
            setattr(invoice, key, val)

    # Re-validate after correction
    validation = validate_invoice(invoice.to_dict(), db, invoice_id)
    invoice.validation_errors = {"errors": validation.errors, "warnings": validation.warnings}
    db.commit()

    # Update vendor learning
    if invoice.vendor_name:
        try:
            client = ClaudeExtractionClient()
            hints = await client.generate_layout_hints(original, corrections)
            profile = get_or_create_profile(db, invoice.vendor_name, invoice.vendor_email)
            apply_layout_hints(db, profile, hints)
        except Exception as e:
            logger.warning("Vendor learning update failed: %s", e)

    _log(db, invoice_id, "corrected", details={"corrections": corrections})
    return invoice.to_dict()


# ─────────────────────────────────────── approve ───────────────────────────────

@router.post("/{invoice_id}/approve")
def approve_invoice(
    invoice_id: int,
    user: str = "system",
    db: Session = Depends(get_db),
):
    invoice = _get_or_404(db, invoice_id)
    if invoice.status not in (InvoiceStatus.EXTRACTED, InvoiceStatus.NEEDS_REVIEW):
        raise HTTPException(400, f"Cannot approve invoice in status: {invoice.status}")

    # Post to ERP
    try:
        erp_result = active_connector.post_invoice(invoice.to_dict())
        invoice.erp_post_result = erp_result
        invoice.status = InvoiceStatus.POSTED
    except Exception as e:
        invoice.status = InvoiceStatus.APPROVED
        invoice.erp_post_result = {"error": str(e)}

    invoice.approved_by = user
    invoice.approved_at = datetime.utcnow()
    db.commit()

    _log(db, invoice_id, "approved", user=user, details={"erp_result": invoice.erp_post_result})
    return invoice.to_dict()


# ─────────────────────────────────────── delete ────────────────────────────────

@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    """Delete an invoice and its associated file from disk."""
    invoice = _get_or_404(db, invoice_id)

    # Delete file from disk
    if invoice.file_path and os.path.exists(invoice.file_path):
        try:
            os.remove(invoice.file_path)
        except Exception as e:
            logger.warning("Could not delete file %s: %s", invoice.file_path, e)

    db.delete(invoice)
    db.commit()
    return {"deleted": True, "invoice_id": invoice_id}


# ─────────────────────────────────────── stats ─────────────────────────────────

@stats_router.get("/accuracy")
def vendor_accuracy(db: Session = Depends(get_db)):
    profiles = db.query(VendorProfile).order_by(VendorProfile.invoice_count.desc()).all()
    return [
        {
            "vendor_name": p.vendor_name,
            "invoice_count": p.invoice_count,
            "avg_confidence": round(p.avg_confidence, 3),
            "last_invoice_at": p.last_invoice_at.isoformat() if p.last_invoice_at else None,
        }
        for p in profiles
    ]


@stats_router.get("/dashboard")
def dashboard_stats(db: Session = Depends(get_db)):
    total = db.query(Invoice).count()
    by_status = dict(
        db.query(Invoice.status, func.count(Invoice.id))
        .group_by(Invoice.status)
        .all()
    )
    avg_conf = db.query(func.avg(Invoice.confidence_score)).scalar() or 0.0
    return {
        "total_invoices": total,
        "by_status": by_status,
        "avg_confidence": round(float(avg_conf), 3),
    }


# ─────────────────────────────────────── helpers ───────────────────────────────

def _get_or_404(db: Session, invoice_id: int) -> Invoice:
    invoice = db.query(Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(404, f"Invoice {invoice_id} not found")
    return invoice


def _log(db: Session, invoice_id: int, action: str, user: str = None, details: dict = None):
    db.add(AuditLog(invoice_id=invoice_id, action=action, user=user, details=details))
    db.commit()


def _ensure_storage():
    os.makedirs(settings.storage_path, exist_ok=True)


async def _process_async(invoice_id: int):
    """Fallback: run the pipeline in-process when Celery is unavailable."""
    from ..workers.celery_tasks import _run_pipeline
    try:
        await _run_pipeline(invoice_id)
    except Exception as e:
        logger.error("In-process pipeline failed for invoice %d: %s", invoice_id, e)
