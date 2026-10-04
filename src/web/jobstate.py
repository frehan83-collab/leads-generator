"""Single source of truth for background-job running flags.

Settings/campaigns routes set these when they spawn threaded jobs;
the API and dashboard read them for live status. Thread-safe.
"""

import threading

_lock = threading.Lock()
_flags = {
    "pipeline": False,
    "sending": False,
    "emailing": False,
}


def _key(name: str) -> str:
    return {"pipeline": "pipeline", "sending": "sending", "emailing": "emailing"}.get(
        name, name
    )


def set_running(name: str, value: bool) -> None:
    with _lock:
        _flags[_key(name)] = bool(value)


def is_running(name: str) -> bool:
    with _lock:
        return bool(_flags.get(_key(name), False))


def snapshot() -> dict:
    with _lock:
        return {
            "pipeline": bool(_flags.get("pipeline", False)),
            "sending": bool(_flags.get("sending", False)),
            "emailing": bool(_flags.get("emailing", False)),
        }
