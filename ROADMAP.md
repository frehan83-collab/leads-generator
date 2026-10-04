# Roadmap — Sperton Sales Platform

Living document. Updated 2026-10-04 after autonomous hardening session.
Code is truth; this file tracks direction, not status.

## Internal assessment (2026-10-04)

**State:** Working, feature-rich, single-operator tool. Real pipeline
(multi-source scrape → BRREG/Snov enrichment → AI drafts → Resend/Snov
outreach → CRM), polished dark UI, 123 passing tests. Not yet
production-grade for unattended multi-user operation.

**Structural risks (ranked):**
1. Sequential pipeline + 1.1s Snov sleeps → multi-hour runs; no credit budget/stop.
2. No auth on dashboard; Flask dev server; SQLite single-file.
3. Silent `None` error propagation in Snov client (can't tell empty from failed).
4. Scraper selector fragility (no health checks); website crawl has no robots.txt respect or page budget.
5. Dual send paths (Snov vs Resend) with split source-of-truth.

## Done (2026-10-04 session)

- [x] DB init ordering fix (fresh-DB crash), PRAGMA-checked migrations, FK enforcement
- [x] Column allowlists on dynamic updates, LIKE-escape on search filters
- [x] `src/config.py` central settings; no committed secrets; `.env.example`
- [x] Follow-ups default to draft-awaiting-approval; double-send guard
- [x] Idempotent logging, `pytest.ini`, pinned `requirements.txt`
- [x] Fixed silent stealth no-op (playwright-stealth 2.x API)
- [x] 404/500 pages, A/B nav link, flash auto-dismiss, live status polling
- [x] 9 hardening tests; suite 97→123 green; junk/dead-code cleanup; README rewrite

## Next, highest value first

### P0 — Reliability (before any scale-up)
- [ ] Bounded parallel `_process_posting` (workers + Snov credit limiter + per-domain timeout)
- [ ] Typed Snov errors (`SnovError`, `OutOfCredits`, `RateLimited`) instead of silent `None`; surface in `pipeline_runs.error_message`
- [ ] Merge website + Snov prospects (no early-return); atomic posting+prospect transaction
- [ ] Dashboard auth (at minimum HTTP basic + bind 127.0.0.1) before any network exposure; replace dev server with waitress/gunicorn

### P1 — Quality
- [ ] `BaseScraper` (shared context/cookies/goto); selector health-check tests; snapshot-on-fail
- [ ] Website scraper: httpx fast path first, Playwright fallback; max 3 contact paths; robots.txt respect; per-run page budget
- [ ] BRREG via client everywhere + org_number caching; backoff on 5xx; close session
- [ ] Unify send queue: `approved → scheduled → sent` through one sender; bounce/suppression list; Resend retry

### P2 — Operability
- [ ] Structured JSON logs + `/healthz` endpoint + Snov-credit low-water alert
- [ ] `requirements-dev.txt`, CI (pytest + ruff), pre-commit hooks
- [ ] Archive root `test_*.py` live scripts → `manual/`; retire `migrate_database.py` (superseded by `db._migrate`)
- [ ] Postgres path (`DATABASE_URL`) when multi-user/concurrency is needed

### P3 — Growth
- [ ] Additional sources (LinkedIn jobs via API partners, company career pages)
- [ ] Lead scoring v2 (firmographic fit + engagement signals, calibrated on won/lost)
- [ ] Multi-user roles, audit log, per-seat Snov budgets
