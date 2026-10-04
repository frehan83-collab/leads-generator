"""Pagination helpers: validated per-page sizes with session memory."""

PAGE_SIZES = (25, 50, 100, 200)
DEFAULT_PAGE_SIZE = 50


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
