"""Pagination helpers: validated per-page sizes with session memory."""

PAGE_SIZES = (25, 50, 100, 200)
DEFAULT_PAGE_SIZE = 50

AGE_OPTIONS = ("7", "14", "30")  # days; absence means all time


def page_size(default: int = DEFAULT_PAGE_SIZE) -> int:
    """Resolve rows-per-page: ?per_page= query param wins (and is remembered
    in the session), otherwise the remembered value, otherwise the default.
    Anything outside PAGE_SIZES falls back to the default.
    """
    from flask import request, session

    raw = request.args.get("per_page")
    if raw is not None:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        if value not in PAGE_SIZES:
            value = default
        session["per_page"] = value
        return value
    remembered = session.get("per_page", default)
    return remembered if remembered in PAGE_SIZES else default


def age_filter() -> tuple[int | None, str]:
    """Validated ?older_than= (7/14/30 days) for pruning views.

    Returns (days_or_None, raw_string_for_template). Deliberately NOT
    remembered in the session: destructive filters stay explicit in the URL.
    """
    from flask import request

    raw = (request.args.get("older_than") or "").strip()
    if raw in AGE_OPTIONS:
        return int(raw), raw
    return None, ""
