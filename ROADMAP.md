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

## Done (2026-10-04 sessions)

### Session 1 — hardening
- [x] DB init ordering fix (fresh-DB crash), PRAGMA-checked migrations, FK enforcement
- [x] Column allowlists on dynamic updates, LIKE-escape on search filters
- [x] `src/config.py` central settings; no committed secrets; `.env.example`
- [x] Follow-ups default to draft-awaiting-approval; double-send guard
- [x] Idempotent logging, `pytest.ini`, pinned `requirements.txt`
- [x] Fixed silent stealth no-op (playwright-stealth 2.x API)
- [x] 404/500 pages, A/B nav link, flash auto-dismiss, live status polling
- [x] 9 hardening tests; suite 97→123 green; junk/dead-code cleanup; README rewrite

### Session 2 — P0 reliability
- [x] Typed Snov errors (`SnovError`/`SnovAuthError`/`SnovOutOfCredits`); explicit
  API failures propagate, transport failures degrade; fatal errors abort runs
  with `error_message` on the `pipeline_runs` record
- [x] Website+Snov merge: Snov fallback runs when website yields nothing storable
  (credits spent only where needed); `update_job_posting` allowlisted helper
- [x] Bounded parallel processing (`PIPELINE_WORKERS`, default 1 = sequential);
  per-worker browsers, WAL+busy_timeout, per-domain deadline (`DOMAIN_TIMEOUT_SEC`)
- [x] Credit guard: zero-balance and `SNOV_MIN_CREDITS` abort before burning hours
- [x] Dashboard basic auth (`DASHBOARD_USER`/`DASHBOARD_PASS`, webhook exempt);
  waitress production server with dev fallback
- [x] 14 new tests (Snov errors, pipeline merge/abort/parallel, auth); suite → 137 green

## Next, highest value first

### P0 — Reliability (before any scale-up)
- [x] Bounded parallel `_process_posting` (workers + Snov credit limiter + per-domain timeout)
- [x] Typed Snov errors instead of silent `None`; surfaced in `pipeline_runs.error_message`
- [x] Merge website + Snov prospects (no early-return); idempotent resume via UNIQUE keys
  (full cross-network atomicity intentionally not done — network interleaving;
  UNIQUE-key idempotency is the correct pattern)
- [x] Dashboard auth (basic + webhook exempt) and waitress server

### P1 — Quality
- [x] `BaseScraper` (`src/scraper/base.py`: shared context, cookies, selector
  health, failure snapshots); all 5 job scrapers + website migrated; fixed
  browser/context leaks on exceptions; 8 parser health tests
- [x] Website scraper: plain-HTTP fast path first (no browser when a personal
  address is found), robots.txt honored (site blocks + path filtering),
  per-domain deadline enforced in both loops; 4 fast-path/robots tests
- [x] BRREG via client everywhere (`search_by_name` added, raw requests call
  removed); session close + lazy recreate; 4 client tests; pipeline closes
  session per run
- [x] Unified send queue guards: suppression list (bounce/complaint via webhook),
  both senders honor `scheduled_for`, Resend retry (transport/429 only);
  fixed `scheduled_for` missing from send query + `now` shadowing early-send
  bug; 9 suppression/queue tests
- [ ] (remaining) Per-run page budget cap beyond deadline; httpx upgrade (optional)

### P2 — Operability
- [x] Structured JSON logs (`LOG_FORMAT=json`, console + rotating file)
- [x] `/healthz` endpoint (process + DB counts, auth-exempt, 503 when degraded)
- [x] Snov-credit low-water alert (`SNOV_LOW_WATER_CREDITS`, warning + webhook)
- [x] `requirements-dev.txt`, ruff clean (`check` enforced, `format` applied),
  rewritten CI (3.12, both requirement files, lint + tests), pre-commit hooks
- [x] Root live scripts → `manual/` (+README); `migrate_database.py` retired
  (superseded by `db._migrate` v2); `LEADS_DB_PATH` override
- [ ] Postgres path (`DATABASE_URL`) — **deferred deliberately**: single-writer
  SQLite + WAL + busy_timeout is correct for single-operator use; revisit only
  when multi-user concurrency is actually needed

### P3 — Growth
- [ ] Additional sources (LinkedIn jobs via API partners, company career pages)
- [ ] Lead scoring v2 (firmographic fit + engagement signals, calibrated on won/lost)
- [ ] Multi-user roles, audit log, per-seat Snov budgets
