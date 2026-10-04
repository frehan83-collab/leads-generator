"""Campaigns page — review, edit, approve, and send email drafts."""

import logging
import os
import threading
from datetime import UTC, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src.database import db
from src.emails.drafter import regenerate_draft
from src.emails.templates import TEMPLATES
from src.web.auth import audit

campaigns_bp = Blueprint("campaigns", __name__)
logger = logging.getLogger(__name__)

_sending_running = False


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

    # Counts per status for tab badges (single SQL query)
    status_counts = db.get_draft_status_counts()

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

    # F1: Email events for activity timeline
    email_events = db.get_email_events_by_draft(draft_id)

    # F3: Sequence chain for this prospect
    sequence = db.get_draft_sequence(draft["prospect_id"])

    # F4: LinkedIn message for this draft
    linkedin_msg = db.get_linkedin_message_by_draft(draft_id)

    # F5: AI variants
    variants = db.get_draft_variants(draft_id)

    return render_template(
        "draft_detail.html",
        draft=draft,
        templates=TEMPLATES,
        email_events=email_events,
        sequence=sequence,
        linkedin_msg=linkedin_msg,
        variants=variants,
    )


@campaigns_bp.route("/campaigns/<int:draft_id>/approve", methods=["POST"])
def approve(draft_id):
    draft = db.get_email_draft_by_id(draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for("campaigns.campaigns"))

    db.update_email_draft(
        draft_id,
        {
            "status": "approved",
            "approved_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        },
    )
    audit("draft.approve", "email_draft", draft_id, draft.get("prospect_email", ""))
    flash(f"Draft approved for {draft.get('prospect_email', '')}", "success")
    return redirect(request.referrer or url_for("campaigns.campaigns"))


@campaigns_bp.route("/campaigns/<int:draft_id>/edit", methods=["POST"])
def edit(draft_id):
    subject = request.form.get("subject", "").strip()
    body = request.form.get("body", "").strip()

    if not subject or not body:
        flash("Subject and body are required.", "error")
        return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))

    db.update_email_draft(
        draft_id, {"subject": subject, "body": body, "status": "draft"}
    )
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


@campaigns_bp.route("/campaigns/send-all-approved", methods=["POST"])
def send_all_approved():
    """Bulk-send all approved drafts to Snov.io in background."""
    global _sending_running
    if _sending_running:
        flash("Send job is already running.", "warning")
        return redirect(url_for("campaigns.campaigns"))

    _sending_running = True

    def _run():
        global _sending_running
        try:
            from src.outreach.sender import send_approved_drafts

            send_approved_drafts()
        except Exception as exc:
            logger.error("Bulk send failed: %s", exc, exc_info=True)
        finally:
            _sending_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    audit("drafts.bulk_send_snov", "email_draft", "", "all approved")
    flash("Sending all approved drafts to Snov.io...", "success")
    return redirect(url_for("campaigns.campaigns", status="approved"))


@campaigns_bp.route("/campaigns/<int:draft_id>/send", methods=["POST"])
def send_single(draft_id):
    """Send a single approved draft to Snov.io immediately."""
    from src.snov.client import SnovClient

    draft = db.get_email_draft_by_id(draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for("campaigns.campaigns"))

    if draft["status"] != "approved":
        flash("Only approved drafts can be sent.", "warning")
        return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))

    snov_list_id = os.getenv("SNOV_LIST_ID")
    if not snov_list_id:
        flash("SNOV_LIST_ID not configured.", "error")
        return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))

    try:
        snov = SnovClient()
        prospect = {
            "email": draft["prospect_email"],
            "first_name": draft.get("first_name", ""),
            "last_name": draft.get("last_name", ""),
            "full_name": draft.get("prospect_name", ""),
            "position": draft.get("prospect_title", ""),
            "company_name": draft.get("company_name", ""),
            "company_domain": draft.get("company_domain", ""),
        }
        added = snov.add_prospect_to_list(snov_list_id, prospect)

        if added:
            now = datetime.now(UTC).replace(tzinfo=None).isoformat()
            db.update_email_draft(draft_id, {"status": "sent", "sent_at": now})
            db.log_outreach(
                {
                    "prospect_id": draft["prospect_id"],
                    "campaign_id": snov_list_id,
                    "status": "sent_to_snov",
                    "sent_at": now,
                    "notes": f"Manual send of draft #{draft_id}",
                }
            )
            flash(f"Sent to Snov.io: {draft['prospect_email']}", "success")
            audit("draft.send_snov", "email_draft", draft_id, draft["prospect_email"])
        else:
            flash(f"Snov.io did not accept {draft['prospect_email']}.", "error")
    except Exception as exc:
        flash(f"Send failed: {exc}", "error")

    return redirect(request.referrer or url_for("campaigns.campaigns"))


# ── Resend direct-email routes ────────────────────────────────────────

_emailing_running = False


@campaigns_bp.route("/campaigns/<int:draft_id>/send-email", methods=["POST"])
def send_email_single(draft_id):
    """Send a single approved draft directly via Resend."""
    from src.outreach.email_sender import send_email_direct

    result = send_email_direct(draft_id)
    if result["success"]:
        audit("draft.send_resend", "email_draft", draft_id, result.get("resend_id", ""))
        flash(
            f"Email sent directly to prospect (Resend ID: {result.get('resend_id', 'ok')})",
            "success",
        )
    else:
        flash(f"Email send failed: {result['error']}", "error")

    return redirect(request.referrer or url_for("campaigns.campaigns"))


@campaigns_bp.route("/campaigns/email-all-approved", methods=["POST"])
def email_all_approved():
    """Bulk-send all approved drafts directly via Resend in background."""
    global _emailing_running
    if _emailing_running:
        flash("Email send job is already running.", "warning")
        return redirect(url_for("campaigns.campaigns"))

    _emailing_running = True

    def _run():
        global _emailing_running
        try:
            from src.outreach.email_sender import send_all_approved_email

            stats = send_all_approved_email()
            logger.info("Bulk Resend email complete: %s", stats)
        except Exception as exc:
            logger.error("Bulk email send failed: %s", exc, exc_info=True)
        finally:
            _emailing_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    audit("drafts.bulk_send_resend", "email_draft", "", "all approved")
    flash("Sending all approved drafts via email (Resend)...", "success")
    return redirect(url_for("campaigns.campaigns", status="approved"))


# ── LinkedIn outreach routes (F4) ─────────────────────────────────────


@campaigns_bp.route("/campaigns/<int:draft_id>/linkedin-copied", methods=["POST"])
def linkedin_copied(draft_id):
    """Mark LinkedIn message as copied."""
    msg = db.get_linkedin_message_by_draft(draft_id)
    if msg:
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()
        db.update_linkedin_message(msg["id"], {"status": "copied", "copied_at": now})
        flash("LinkedIn message marked as copied.", "success")
    else:
        flash("LinkedIn message not found.", "error")
    return redirect(
        request.referrer or url_for("campaigns.draft_detail", draft_id=draft_id)
    )


@campaigns_bp.route("/campaigns/<int:draft_id>/linkedin-sent", methods=["POST"])
def linkedin_sent(draft_id):
    """Mark LinkedIn message as sent."""
    msg = db.get_linkedin_message_by_draft(draft_id)
    if msg:
        now = datetime.now(UTC).replace(tzinfo=None).isoformat()
        db.update_linkedin_message(msg["id"], {"status": "sent", "sent_at": now})
        flash("LinkedIn message marked as sent.", "success")
    else:
        flash("LinkedIn message not found.", "error")
    return redirect(
        request.referrer or url_for("campaigns.draft_detail", draft_id=draft_id)
    )


@campaigns_bp.route("/campaigns/linkedin")
def linkedin_list():
    """LinkedIn outreach list view."""
    status_filter = request.args.get("status", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20

    messages, total = db.get_linkedin_messages_list(
        status=status_filter or None,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    linkedin_stats = db.get_linkedin_stats()

    return render_template(
        "linkedin.html",
        messages=messages,
        total=total,
        page=page,
        total_pages=total_pages,
        status_filter=status_filter,
        linkedin_stats=linkedin_stats,
    )


# ── AI variant swap route (F5) ────────────────────────────────────────


@campaigns_bp.route(
    "/campaigns/<int:draft_id>/use-variant/<int:variant_id>", methods=["POST"]
)
def use_variant(draft_id, variant_id):
    """Swap draft content with a variant."""
    draft = db.get_email_draft_by_id(draft_id)
    variant = db.get_email_draft_by_id(variant_id)

    if not draft or not variant:
        flash("Draft or variant not found.", "error")
        return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))

    # Swap the content
    db.update_email_draft(
        draft_id,
        {
            "subject": variant["subject"],
            "body": variant["body"],
            "template_name": variant.get("template_name", draft["template_name"]),
            "ai_context": variant.get("ai_context"),
        },
    )

    flash("Draft updated with selected variant.", "success")
    return redirect(url_for("campaigns.draft_detail", draft_id=draft_id))


# ── A/B Testing (C1) ─────────────────────────────────────────────────


@campaigns_bp.route("/campaigns/ab-tests")
def ab_tests():
    """A/B test dashboard showing variant comparisons."""
    groups = db.get_ab_test_groups()
    return render_template("ab_tests.html", groups=groups)


# ── Prospect Profile (C4) ────────────────────────────────────────────


@campaigns_bp.route("/prospects/<int:prospect_id>/profile")
def prospect_profile(prospect_id):
    """Full prospect enrichment profile."""
    profile = db.get_prospect_full_profile(prospect_id)
    if not profile:
        flash("Prospect not found.", "error")
        return redirect(url_for("prospects.prospects"))

    # Compute intent signals if domain available
    intent = None
    if profile.get("company_domain"):
        intent = db.get_company_intent_signals(profile["company_domain"])

    return render_template(
        "prospect_profile.html",
        prospect=profile,
        intent=intent,
    )
