"""
ERA Group Analytics Dashboard — PDF upload and extraction orchestration.
"""

import logging
import os
import json
import tempfile
from pathlib import Path
import threading
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, flash
from src.database import db
from src.era.pdf_extractor import (
    extract_invoice_data_ml,
    extract_contract_data_ml,
    extract_financial_statement_ml,
    extract_generic_data_ml,
)

logger = logging.getLogger(__name__)

era_bp = Blueprint("era", __name__, url_prefix="/era")

# Upload directory
UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "uploads" / "pdf"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@era_bp.route("/")
def dashboard():
    """ERA Group analytics dashboard with upload form."""
    db.init_db()
    stats = db.get_era_dashboard_stats()
    recent_uploads = db.get_pdf_uploads(limit=10)

    return render_template("era_dashboard.html", stats=stats, recent_uploads=recent_uploads)


@era_bp.route("/upload", methods=["POST"])
def upload_pdf():
    """Handle single or multiple PDF uploads (files or folder)."""
    files = request.files.getlist("file")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"success": False, "error": "No files provided"}), 400

    uploaded = []
    skipped = []
    errors = []

    for file in files:
        if not file or file.filename == "":
            continue

        # Support folder uploads: browser sends "subfolder/file.pdf"
        original_name = file.filename
        # Use only the basename for storage
        filename = os.path.basename(original_name)

        if not filename.lower().endswith(".pdf"):
            skipped.append({"filename": original_name, "reason": "Not a PDF"})
            continue

        try:
            file_path = UPLOAD_DIR / filename
            file.save(file_path)
            file_size = os.path.getsize(file_path)

            upload_id = db.insert_pdf_upload(filename, file_size, status="pending")
            if not upload_id:
                skipped.append({"filename": filename, "reason": "Already uploaded"})
                continue

            # Trigger extraction in background thread
            thread = threading.Thread(target=_extract_pdf_background, args=(upload_id, str(file_path)))
            thread.daemon = True
            thread.start()

            uploaded.append({"upload_id": upload_id, "filename": filename})
            logger.info(f"PDF upload started: {filename} (id={upload_id})")

        except Exception as exc:
            errors.append({"filename": filename, "error": str(exc)})
            logger.error(f"PDF upload error for {filename}: {exc}")

    total = len(uploaded)
    if total == 0 and not errors:
        return jsonify({
            "success": False,
            "error": "No new PDF files to process",
            "skipped": skipped,
        }), 400

    return jsonify({
        "success": True,
        "uploaded_count": total,
        "upload_ids": [u["upload_id"] for u in uploaded],
        "uploaded": uploaded,
        "skipped": skipped,
        "errors": errors,
        "message": f"{total} PDF(s) uploaded. Processing...",
    }), 200


@era_bp.route("/status/<int:upload_id>")
def extraction_status(upload_id: int):
    """Check extraction status (for HTMX polling)."""
    uploads = db.get_pdf_uploads(limit=100)
    upload = next((u for u in uploads if u["id"] == upload_id), None)

    if not upload:
        return jsonify({"success": False, "error": "Upload not found"}), 404

    return jsonify({
        "success": True,
        "upload_id": upload_id,
        "status": upload["status"],
        "filename": upload["filename"],
        "processing_time": upload.get("processing_time"),
        "error": upload.get("error_message"),
    }), 200


@era_bp.route("/status/batch")
def batch_status():
    """Check status of multiple uploads by IDs (comma-separated query param)."""
    ids_str = request.args.get("ids", "")
    if not ids_str:
        return jsonify({"success": False, "error": "No IDs provided"}), 400

    ids = [int(i) for i in ids_str.split(",") if i.strip().isdigit()]
    uploads = db.get_pdf_uploads(limit=200)

    results = []
    for uid in ids:
        upload = next((u for u in uploads if u["id"] == uid), None)
        if upload:
            results.append({
                "upload_id": uid,
                "status": upload["status"],
                "filename": upload["filename"],
                "processing_time": upload.get("processing_time"),
                "error": upload.get("error_message"),
            })

    all_done = all(r["status"] in ("completed", "error") for r in results)
    completed = sum(1 for r in results if r["status"] == "completed")
    errored = sum(1 for r in results if r["status"] == "error")
    processing = sum(1 for r in results if r["status"] in ("pending", "processing"))

    return jsonify({
        "success": True,
        "all_done": all_done,
        "completed": completed,
        "errored": errored,
        "processing": processing,
        "total": len(results),
        "results": results,
    }), 200


# ------------------------------------------------------------------
# Background Processing
# ------------------------------------------------------------------

def _extract_pdf_background(upload_id: int, pdf_path: str):
    """Extract PDF in background thread."""
    import time
    start_time = time.time()

    try:
        db.init_db()
        db.update_pdf_status(upload_id, "processing")

        # Detect document type (invoice, contract, statement, or generic)
        doc_type = _detect_document_type(pdf_path)
        logger.info(f"Detected document type: {doc_type}")

        # Extract data based on type
        if doc_type == "invoice":
            result = extract_invoice_data_ml(pdf_path)
        elif doc_type == "contract":
            result = extract_contract_data_ml(pdf_path)
        elif doc_type == "statement":
            result = extract_financial_statement_ml(pdf_path)
        else:
            result = extract_generic_data_ml(pdf_path)

        # Store extraction if successful
        if result.get("success"):
            extraction_data = json.dumps(result.get("data", {}))
            field_count = _count_extracted_fields(result.get("data", {}))

            db.insert_extraction(
                pdf_id=upload_id,
                extraction_type=doc_type,
                extracted_data=extraction_data,
                confidence_score=result.get("confidence", 0.0),
                page_number=1,
                field_count=field_count,
            )

            processing_time = int(time.time() - start_time)
            db.update_pdf_status(upload_id, "completed", processing_time=processing_time)
            logger.info(f"PDF extraction completed for upload {upload_id} ({doc_type}) in {processing_time}s")
        else:
            error_msg = result.get("error", "Unknown error")
            processing_time = int(time.time() - start_time)
            db.update_pdf_status(upload_id, "error", error_message=error_msg, processing_time=processing_time)
            logger.error(f"PDF extraction failed for upload {upload_id}: {error_msg}")

    except Exception as exc:
        error_msg = str(exc)
        processing_time = int(time.time() - start_time)
        db.update_pdf_status(upload_id, "error", error_message=error_msg, processing_time=processing_time)
        logger.error(f"Background extraction error for upload {upload_id}: {exc}", exc_info=True)


def _detect_document_type(pdf_path: str) -> str:
    """Detect document type from content."""
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            # Get first page text
            first_page_text = (pdf.pages[0].extract_text() or "").lower() if pdf.pages else ""

            # Simple heuristics
            if any(word in first_page_text for word in ["invoice", "invoice no", "inv.", "bill", "faktura", "fakturanr", "fakturanummer"]):
                return "invoice"
            elif any(word in first_page_text for word in ["contract", "agreement", "between", "kontrakt", "avtale"]):
                return "contract"
            elif any(word in first_page_text for word in ["balance sheet", "income statement", "cash flow", "p&l", "balanse", "resultatregnskap"]):
                return "statement"

    except Exception as exc:
        logger.debug(f"Document type detection error: {exc}")

    return "generic"


def _count_extracted_fields(data: dict) -> int:
    """Count number of extracted fields."""
    if isinstance(data, dict):
        return len([v for v in data.values() if v is not None and v != "" and v != []])
    return 0
