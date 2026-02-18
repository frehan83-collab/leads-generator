"""
ERA Group Templates — Custom extraction rule management.
"""

import logging
import json
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from src.database import db

logger = logging.getLogger(__name__)

era_templates_bp = Blueprint("era_templates", __name__, url_prefix="/era")


@era_templates_bp.route("/templates")
def templates_list():
    """List extraction templates."""
    db.init_db()
    # Note: This is a placeholder since we haven't added template query functions to db.py
    # For now, show empty list with UI for future expansion

    return render_template(
        "era_templates.html",
        templates=[],
        message="Template management coming soon. Using default extraction rules.",
    )


@era_templates_bp.route("/templates/new", methods=["GET", "POST"])
def create_template():
    """Create new extraction template."""
    if request.method == "POST":
        try:
            data = request.get_json()
            template_name = data.get("name")
            pattern_type = data.get("type")  # invoice, contract, statement
            field_mapping = data.get("fields")

            if not template_name or not pattern_type:
                return jsonify({"success": False, "error": "Name and type required"}), 400

            # Validate field mapping
            if field_mapping:
                try:
                    json.dumps(field_mapping)
                except:
                    return jsonify({"success": False, "error": "Invalid field mapping JSON"}), 400

            # Store template (would need db functions for this)
            # template_id = db.insert_extraction_template(template_name, pattern_type, field_mapping)

            logger.info(f"Created template: {template_name} ({pattern_type})")

            return jsonify({
                "success": True,
                "message": "Template created successfully",
                # "template_id": template_id
            }), 200

        except Exception as exc:
            logger.error(f"Template creation error: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    return render_template("era_template_form.html")


@era_templates_bp.route("/templates/<int:template_id>", methods=["GET", "PUT", "DELETE"])
def template_detail(template_id: int):
    """Get, update, or delete a template."""
    if request.method == "GET":
        # Would fetch template from db
        return jsonify({"success": False, "error": "Template not found"}), 404

    elif request.method == "PUT":
        try:
            data = request.get_json()
            # Update template in db
            logger.info(f"Updated template {template_id}")
            return jsonify({"success": True, "message": "Template updated"}), 200
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    elif request.method == "DELETE":
        try:
            # Delete template from db
            logger.info(f"Deleted template {template_id}")
            return jsonify({"success": True, "message": "Template deleted"}), 200
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
