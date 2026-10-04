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
- [x] Additional source: company career pages (`careers` source — bounded
  revisits of known domains, robots honored, same-domain links only,
  stable URL-hash IDs, 5 tests)
- [x] Lead scoring v2 (`src/scoring/`: fit 40 + demand 35 + engagement 25,
  explainable components, `lead_scores` table, pipeline hook,
  win-rate calibration report; 7 tests)
- [x] Audit log (`audit_log` table, actor from dashboard auth, hooks on
  approve/send/bulk-send/delete/stage-move/keyword changes; 2 tests)
- [ ] Multi-user roles, per-seat Snov budgets — **deferred deliberately**:
  needs session auth + tenant model; current basic-auth + audit log is the
  correct foundation, not a substitute. Build when a second operator exists.

### Beyond the roadmap — product surface + verification
- [x] Scoring v2 wired in: dashboard hot widget (fixed v1 always-0 score),
  `/scores` leaderboard + calibration page, profile score card, score/level
  in CSV/Excel/PDF exports, `--status` top scores
- [x] Runtime verification: booted production server (waitress), all 11 routes
  200, `/healthz` against the real DB (75 postings, 128 prospects),
  `--status` live incl. Snov balance
- [ ] Production data note: `companies` table is empty (BRREG import never run)
  — run `import_brreg_companies.py` to unlock full v2 fit scoring; v2 degrades
  gracefully until then

### World-class batch 2 — live ops, briefs, A/B loop
- [x] Unified job state (`src/web/jobstate.py` — fixed split-brain flags:
  campaigns and settings had separate `_sending_running` globals)
- [x] Live run progress (`/api/run-progress` + dashboard auto-refresh strip);
  stale-run detection (>12h “running” → `stale`, amber badge + CSS)
- [x] Pre-meeting briefs (`src/emails/briefing.py` + `/brief` route + template:
  company facts, open roles, relationship timeline, rule-based talking
  points, stage-aware next step; audit-logged views)
- [x] A/B winner upgrade (reply×10 + click×3 + opens, 3-signal minimum,
  “collecting data” state instead of premature winners)
- [x] `PIPELINE_WORKERS` default 1→2, hard-capped at 4
- [x] 10 new tests; suite 185 → 195 green; ruff clean; runtime-verified live

### World-class batch 3 — ops polish + BRREG backfill
- [x] Stale-run auto-mark on pipeline start (`mark_stale_runs`, T/space-safe)
- [x] Scheduler time correctness: `HH:MM` validation fail-fast + server-local
  timezone logged (docs corrected — `schedule` is local-time, not UTC)
- [x] BRREG backfill: 200 aquaculture companies + fixed `extract_decision_makers`
  (role code lives in `type.kode`, not `rolle.kode`; string-`navn` shape);
  788 decision-makers stored; `--backfill-roles` mode added
- [x] Scoring match overhaul: org → normalized website → fuzzy name fallback,
  case-insensitive domain identity everywhere; fit now lands on real data
  (AquaGen 40/40)
- [x] Recent-exports listing on settings page
- [x] 6 new tests; suite 195 → 201 green; ruff clean

### World-class batch 4 — posting lifecycle (campaigns track live ads)
- [x] `status` (`active`/`expired`/`unknown`) + `last_checked_at` on postings;
  fresh scrapes are `active`, legacy rows `unknown`; v9 migration
- [x] Conservative revalidator (`src/scraper/revalidate.py`): 404/410 + explicit
  expired markers only; blocks/unknowns never flip a live ad
- [x] Bounded pipeline step (count + age + time budget) with run stats
  (`postings_revalidated`, `postings_expired`; v10 migration)
- [x] Send guards: both senders + follow-up creation refuse expired-posting
  drafts; draft-detail banner; brief status dots
- [x] Intent/demand/counts exclude expired postings
- [x] 12 new tests; ruff clean

### World-class batch 5 — table prefs, lead quality, domain recall
- [x] Rows-per-page selector (25/50/100/200) on postings/prospects/campaigns/
  LinkedIn, remembered per session; fixed hardcoded ×25 range text and the
  dropped company filter in prospects pagination
- [x] Lead quality (`src/scoring/lead_quality.py`): role-inbox detection
  (conservative set — hr/sales/kontakt stay eligible) + identity confidence;
  hot widget excludes role inboxes; prospects table badges
- [x] BRREG-website domain fallback (`db.get_company_website`: org → fuzzy
  name) ahead of paid Snov lookup — Mowi-class misses now resolve free
- [x] 9 new tests; suite 213 → 222 green; ruff clean
