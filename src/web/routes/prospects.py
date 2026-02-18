"""Prospects page — filterable table with CSV, Excel and PDF export."""

from flask import Blueprint, render_template, request, Response

from src.database import db
from src.export.csv_exporter import (
    stream_prospects_csv,
    build_prospects_xlsx,
    build_prospects_pdf,
)

prospects_bp = Blueprint("prospects", __name__)


@prospects_bp.route("/prospects")
def prospects():
    search = request.args.get("search", "").strip()
    email_status = request.args.get("email_status", "").strip()
    company = request.args.get("company", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50

    rows, total = db.get_prospects_filtered(
        search=search or None,
        email_status=email_status or None,
        company=company or None,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "prospects.html",
        prospects=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        email_status=email_status,
        company=company,
    )


@prospects_bp.route("/prospects/export", endpoint="export_csv_compat")
def export_csv_compat():
    """Legacy CSV export URL — redirect to /prospects/export/csv."""
    return export_csv()


@prospects_bp.route("/prospects/export/csv")
def export_csv():
    """Stream CSV download of all prospects."""
    return Response(
        stream_prospects_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=prospects.csv"},
    )


@prospects_bp.route("/prospects/export/xlsx")
def export_xlsx():
    """Return Excel (.xlsx) download of all prospects."""
    data = build_prospects_xlsx()
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=prospects.xlsx"},
    )


@prospects_bp.route("/prospects/export/pdf")
def export_pdf():
    """Return PDF download of all prospects."""
    data = build_prospects_pdf()
    return Response(
        data,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=prospects.pdf"},
    )
