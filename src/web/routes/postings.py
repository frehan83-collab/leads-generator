"""Job postings page — searchable/filterable table with CSV, Excel and PDF export."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify

from src.database import db
from src.export.csv_exporter import (
    stream_postings_csv,
    build_postings_xlsx,
    build_postings_pdf,
)

postings_bp = Blueprint("postings", __name__)


@postings_bp.route("/postings")
def postings():
    search = request.args.get("search", "").strip()
    keyword = request.args.get("keyword", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50

    rows, total = db.get_job_postings(
        search=search or None,
        keyword=keyword or None,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    keywords = db.get_all_keywords()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "postings.html",
        postings=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        search=search,
        keyword=keyword,
        keywords=keywords,
    )


@postings_bp.route("/postings/export", endpoint="export_csv_compat")
def export_csv_compat():
    """Legacy CSV export URL — redirect to /postings/export/csv."""
    return export_csv()


@postings_bp.route("/postings/export/csv")
def export_csv():
    """Stream CSV download of all job postings."""
    return Response(
        stream_postings_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=postings.csv"},
    )


@postings_bp.route("/postings/export/xlsx")
def export_xlsx():
    """Return Excel (.xlsx) download of all job postings."""
    data = build_postings_xlsx()
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=postings.xlsx"},
    )


@postings_bp.route("/postings/export/pdf")
def export_pdf():
    """Return PDF download of all job postings."""
    data = build_postings_pdf()
    return Response(
        data,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=postings.pdf"},
    )


@postings_bp.route("/postings/delete", methods=["POST"])
def delete_postings():
    """Bulk-delete selected postings (cascades to prospects + drafts)."""
    ids = request.form.getlist("posting_ids")
    posting_ids = [int(i) for i in ids if i.isdigit()]

    if not posting_ids:
        flash("No postings selected.", "warning")
        return redirect(url_for("postings.postings"))

    deleted = db.delete_job_postings(posting_ids)
    flash(f"Deleted {deleted} posting{'s' if deleted != 1 else ''} and related prospects/drafts.", "success")

    # Preserve current filters when redirecting back
    search = request.form.get("search", "")
    keyword = request.form.get("keyword", "")
    page = request.form.get("page", "1")
    return redirect(url_for("postings.postings", search=search, keyword=keyword, page=page))
