"""Public one-click unsubscribe (RFC 8058). No login required."""

import logging

from flask import Blueprint, render_template_string, request

from src.outreach.unsubscribe import process_unsubscribe_token

unsubscribe_bp = Blueprint("unsubscribe", __name__)
logger = logging.getLogger(__name__)

_CONFIRM = """
{% extends "base.html" %}
{% block title %}Meld av{% endblock %}
{% block content %}
<div class="max-w-lg mx-auto text-center py-16">
    <h1 class="text-xl font-semibold text-slate-200 mb-2">Meld deg av e-poster</h1>
    <p class="text-sm text-slate-500 mb-8">Unsubscribe from Sperton outreach emails.</p>
    <form method="post">
        <button type="submit" class="btn-danger">Meld av / Unsubscribe</button>
    </form>
</div>
{% endblock %}
"""

_DONE = """
{% extends "base.html" %}
{% block title %}Avmeldt{% endblock %}
{% block content %}
<div class="max-w-lg mx-auto text-center py-16">
    <h1 class="text-xl font-semibold text-slate-200 mb-2">Du er avmeldt</h1>
    <p class="text-sm text-slate-500">You are unsubscribed. You will receive no further outreach emails.</p>
</div>
{% endblock %}
"""


@unsubscribe_bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    if request.method == "POST":
        email = process_unsubscribe_token(token)
        if email:
            logger.info("Unsubscribed %s via one-click link", email)
            return render_template_string(_DONE), 200
        return render_template_string(_DONE), 200  # same response, no oracle
    return render_template_string(_CONFIRM), 200
