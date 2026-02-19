"""
ERA Group Extractions — View and export extracted data.
"""

import io
import logging
import json
from flask import Blueprint, render_template, request, send_file, jsonify
from src.database import db
from src.export.csv_exporter import (
    export_era_extractions_csv,
    build_era_extractions_xlsx,
    build_era_extractions_pdf,
    build_era_single_extraction_pdf,
)

logger = logging.getLogger(__name__)

era_extractions_bp = Blueprint("era_extractions", __name__, url_prefix="/era")


@era_extractions_bp.route("/extractions")
def extractions_list():
    """View all extractions in a table."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()

    # Parse JSON data for display
    for extraction in extractions:
        try:
            if isinstance(extraction.get("extracted_data"), str):
                extraction["data_preview"] = json.loads(extraction["extracted_data"])
            else:
                extraction["data_preview"] = extraction.get("extracted_data", {})
        except json.JSONDecodeError:
            extraction["data_preview"] = {}

    return render_template(
        "era_extractions.html",
        extractions=extractions,
        extraction_count=len(extractions),
    )


@era_extractions_bp.route("/extractions/<int:extraction_id>")
def extraction_detail(extraction_id: int):
    """View detailed extraction data."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    extraction = next((e for e in extractions if e.get("id") == extraction_id), None)

    if not extraction:
        return "Extraction not found", 404

    # Parse JSON data
    try:
        if isinstance(extraction.get("extracted_data"), str):
            extraction["data"] = json.loads(extraction["extracted_data"])
        else:
            extraction["data"] = extraction.get("extracted_data", {})
    except json.JSONDecodeError:
        extraction["data"] = {}

    return render_template("era_extraction_detail.html", extraction=extraction)


@era_extractions_bp.route("/extractions/export/csv")
def export_csv():
    """Export all extractions to CSV."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    csv_io = export_era_extractions_csv(extractions)
    csv_bytes = io.BytesIO(csv_io.getvalue().encode("utf-8-sig"))
    return send_file(
        csv_bytes,
        mimetype="text/csv",
        as_attachment=True,
        download_name="era_extractions.csv",
    )


@era_extractions_bp.route("/extractions/export/xlsx")
def export_xlsx():
    """Export all extractions to Excel."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    xlsx_bytes = build_era_extractions_xlsx(extractions)
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="era_extractions.xlsx",
    )


@era_extractions_bp.route("/extractions/export/pdf")
def export_pdf():
    """Export all extractions to PDF."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    pdf_bytes = build_era_extractions_pdf(extractions)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="era_extractions.pdf",
    )


@era_extractions_bp.route("/extractions/<int:extraction_id>/export/csv")
def export_single_csv(extraction_id: int):
    """Export one extraction to CSV."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    extraction = next((e for e in extractions if e.get("id") == extraction_id), None)
    if not extraction:
        return "Extraction not found", 404
    csv_io = export_era_extractions_csv([extraction])
    csv_bytes = io.BytesIO(csv_io.getvalue().encode("utf-8-sig"))
    name = (extraction.get("filename") or "extraction").replace(".pdf", "")
    return send_file(csv_bytes, mimetype="text/csv", as_attachment=True, download_name=f"{name}.csv")


@era_extractions_bp.route("/extractions/<int:extraction_id>/export/xlsx")
def export_single_xlsx(extraction_id: int):
    """Export one extraction to Excel (summary + line items)."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    extraction = next((e for e in extractions if e.get("id") == extraction_id), None)
    if not extraction:
        return "Extraction not found", 404
    xlsx_bytes = build_era_extractions_xlsx([extraction])
    name = (extraction.get("filename") or "extraction").replace(".pdf", "")
    return send_file(
        io.BytesIO(xlsx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"{name}.xlsx",
    )


@era_extractions_bp.route("/extractions/<int:extraction_id>/export/pdf")
def export_single_pdf(extraction_id: int):
    """Export one extraction to a detailed PDF."""
    db.init_db()
    extractions = db.get_all_extractions_for_export()
    extraction = next((e for e in extractions if e.get("id") == extraction_id), None)
    if not extraction:
        return "Extraction not found", 404
    pdf_bytes = build_era_single_extraction_pdf(extraction)
    name = (extraction.get("filename") or "extraction").replace(".pdf", "")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{name}_extracted.pdf",
    )


@era_extractions_bp.route("/extractions/<int:extraction_id>/correct", methods=["POST"])
def log_correction(extraction_id: int):
    """Log a user correction for model training."""
    try:
        data = request.get_json()
        field_name = data.get("field")
        corrected_value = data.get("value")

        if not field_name or not corrected_value:
            return jsonify({"success": False, "error": "Missing field or value"}), 400

        # Get original value
        extractions = db.get_all_extractions_for_export()
        extraction = next((e for e in extractions if e.get("id") == extraction_id), None)

        if not extraction:
            return jsonify({"success": False, "error": "Extraction not found"}), 404

        try:
            extracted_data = json.loads(extraction.get("extracted_data", "{}"))
            original_value = extracted_data.get(field_name)
        except json.JSONDecodeError:
            original_value = None

        # Log correction
        correction_id = db.log_correction(extraction_id, field_name, original_value, corrected_value)

        if correction_id:
            logger.info(f"Logged correction for extraction {extraction_id}: {field_name}")
            return jsonify({
                "success": True,
                "correction_id": correction_id,
                "message": "Correction logged. This will help improve model accuracy."
            }), 200
        else:
            return jsonify({"success": False, "error": "Failed to log correction"}), 500

    except Exception as exc:
        logger.error(f"Correction error: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500
