"""Campaigns page — review, edit, approve, and send email drafts."""

from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash

from src.database import db
from src.emails.drafter import regenerate_draft
from src.emails.templates import TEMPLATES

campaigns_bp = Blueprint("campaigns", __name__)


@campaigns_bp.route("/campaigns")
def campaigns():
    status_filter = request.args.get("status", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20

    drafts, total = db.get_email_drafts(
        status=status_filter or None,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Counts per status for tab badges
    all_drafts, _ = db.get_email_drafts(limit=9999)
    status_counts = {}
    for d in all_drafts:
        s = d.get("status", "draft")
        status_counts[s] = status_counts.get(s, 0) + 1

    return render_template(
        "campaigns.html",
        drafts=drafts,
        total=total,
        page=page,
        total_pages=total_pages,
        status_filter=status_filter,
        status_counts=status_counts,
        templates=TEMPLATES,
    )


@campaigns_bp.route("/campaigns/<int:draft_id>")
def draft_detail(draft_id):
    draft = db.get_email_draft_by_id(draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for("campaigns.campaigns"))
    return render_template("draft_detail.html", draft=draft, templates=TEMPLATES)


@campaigns_bp.route("/campaigns/<int:draft_id>/approve", methods=["POST"])
def approve(draft_id):
    draft = db.get_email_draft_by_id(draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for("campaigns.campaigns"))

    db.update_email_draft(draft_id, {
        "status": "approved",
        "approved_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
    })
    flash(f"Draft approved for {draft.get('prospect_email', '')}", "success")
    return redirect(request.referrer or url_for("campaigns.campaigns"))


@campaigns_bp.route("/campaigns/<int:draft_id>/edit", methods=["POST"])
def edit(draft_id):
    subject = request.form.get("subject", "").strip()
    body = request.form.get("body", "").strip()

    if not subject or not body:
        flash("Subject and body are required.", "error")
        return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))

    db.update_email_draft(draft_id, {"subject": subject, "body": body, "status": "draft"})
    flash("Draft updated.", "success")
    return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))


@campaigns_bp.route("/campaigns/<int:draft_id>/regenerate", methods=["POST"])
def regenerate(draft_id):
    template_name = request.form.get("template_name", "").strip()
    ok = regenerate_draft(draft_id, template_name=template_name or None)
    if ok:
        flash("Draft regenerated.", "success")
    else:
        flash("Failed to regenerate draft.", "error")
    return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))
