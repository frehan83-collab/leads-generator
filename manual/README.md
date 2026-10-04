# Manual live-API scripts (NOT part of CI)

These `test_*.py` scripts hit real websites and APIs (Finn.no, NAV,
Snov.io — spending real credits). They are kept for ad-hoc debugging,
not automated testing: `pytest.ini`/`pyproject.toml` scope collection to
`tests/` only.

Run one directly when you need a live check, e.g.:

```bash
python manual/test_live_scraper.py
```

Nothing in here runs in CI or pre-commit.
