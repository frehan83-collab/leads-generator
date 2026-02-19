"""Celery async tasks for invoice processing."""

import logging
import os

from celery import Celery

from ..config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "invoice_ocr",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


async def _run_pipeline(invoice_id: int) -> dict:
    """Core async pipeline — called by both Celery task and sync fallback."""
    from ..models.base import SessionLocal
    from ..models.invoice import Invoice, InvoiceStatus
    from ..extractors import extract
    from ..ai.claude_client import ClaudeExtractionClient
    from ..ai.vendor_learning import get_or_create_profile, update_profile_after_extraction
    from ..validators import validate_invoice

    db = SessionLocal()
    invoice = None
    try:
        invoice = db.query(Invoice).get(invoice_id)
        if not invoice:
            logger.error("Invoice %d not found", invoice_id)
            return {"error": "not found"}

        invoice.status = InvoiceStatus.PROCESSING
        db.commit()

        # 1. Extract raw text / images
        result = extract(invoice.file_path)
        invoice.ocr_text = result.text
        db.commit()

        # 2. Run Claude extraction
        client = ClaudeExtractionClient()
        if invoice.file_format == "pdf" and not result.text.strip():
            # Scanned PDF — send raw PDF directly to Claude vision
            extraction = await client.extract_from_pdf(invoice.file_path)
        elif result.images and result.format in ("pdf_scanned", "image"):
            extraction = await client.extract_from_image(result.images[0], result.text)
        else:
            extraction = await client.extract_from_text(result.text)

        # 3. Validate
        validation = validate_invoice(extraction, db, invoice_id)

        # 4. Persist
        _apply_extraction(invoice, extraction)
        invoice.validation_errors = {
            "errors": validation.errors,
            "warnings": validation.warnings,
        }
        invoice.content_hash = invoice.compute_hash()
        invoice.status = InvoiceStatus.NEEDS_REVIEW if (validation.is_duplicate or validation.needs_review) else InvoiceStatus.EXTRACTED
        db.commit()

        # 5. Vendor learning
        if invoice.vendor_name:
            profile = get_or_create_profile(db, invoice.vendor_name, invoice.vendor_email)
            update_profile_after_extraction(db, profile, extraction, invoice.confidence_score or 0.0)

        logger.info("Invoice %d processed — status: %s", invoice_id, invoice.status)
        return {"status": invoice.status, "invoice_id": invoice_id}

    except Exception as exc:
        logger.exception("Error processing invoice %d: %s", invoice_id, exc)
        if invoice:
            invoice.status = InvoiceStatus.NEEDS_REVIEW
            invoice.processing_error = str(exc)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_invoice_task(self, invoice_id: int):
    """Celery task wrapper around the async pipeline."""
    import asyncio
    try:
        return asyncio.run(_run_pipeline(invoice_id))
    except Exception as exc:
        raise self.retry(exc=exc)


def process_invoice_sync(invoice_id: int):
    """Synchronous fallback when Celery/Redis is unavailable."""
    import asyncio
    return asyncio.run(_run_pipeline(invoice_id))


def _apply_extraction(invoice, extraction: dict):
    """Write extraction dict fields onto the Invoice ORM object."""
    fields = [
        "vendor_name", "vendor_address", "vendor_email", "vendor_phone",
        "invoice_number", "invoice_date", "due_date", "currency",
        "subtotal", "tax_amount", "tax_rate", "total_amount",
        "po_number", "payment_terms", "bank_details",
        "confidence_score", "extraction_notes",
    ]
    for f in fields:
        val = extraction.get(f)
        if val is not None:
            setattr(invoice, f, val)
