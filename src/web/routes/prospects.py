"""Prospects page — filterable table with CSV, Excel and PDF export."""

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from src.database import db
from src.export.csv_exporter import (
    build_prospects_pdf,
    build_prospects_xlsx,
    stream_prospects_csv,
)
from src.web.auth import audit
from src.web.pagination import age_filter, page_size

prospects_bp = Blueprint("prospects", __name__)


@prospects_bp.route("/prospects")
def prospects():
    search = request.args.get("search", "").strip()
    email_status = request.args.get("email_status", "").strip()
    company = request.args.get("company", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = page_size()
    older_than, older_than_raw = age_filter()

    rows, total = db.get_prospects_filtered(
        search=search or None,
        email_status=email_status or None,
        company=company or None,
        limit=per_page,
        offset=(page - 1) * per_page,
        older_than_days=older_than,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    from src.scoring.lead_quality import identity_confidence, is_role_address

    for row in rows:
        row["is_role"] = is_role_address(row.get("email"))
        row["name_conf"] = identity_confidence(row)

    return render_template(
        "prospects.html",
        prospects=rows,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search=search,
        email_status=email_status,
        company=company,
        older_than=older_than_raw,
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


@prospects_bp.route("/prospects/delete", methods=["POST"])
def delete_prospects():
    """Bulk-delete selected prospects (cascades to drafts, stages, outreach).

    Suppressions intentionally survive: a bounced address stays suppressed.
    """
    ids = request.form.getlist("prospect_ids")
    prospect_ids = [int(i) for i in ids if i.isdigit()]

    if not prospect_ids:
        flash("No prospects selected.", "warning")
        return redirect(url_for("prospects.prospects"))

    deleted = db.delete_prospects(prospect_ids)
    audit("prospects.bulk_delete", "prospect", "", f"{deleted} prospects")
    flash(
        f"Deleted {deleted} prospect{'s' if deleted != 1 else ''} and related drafts.",
        "success",
    )
    return redirect(url_for("prospects.prospects"))
