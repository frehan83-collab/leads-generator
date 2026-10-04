# Sperton Sales Platform — Autonomous B2B Lead Engine

Automated recruitment sales and prospecting for Sperton Rekruttering.
Scrapes Norwegian job boards, enriches companies and contacts, drafts
personalized outreach, and manages multichannel follow-up — supervised by
humans, driven by a daily autonomous pipeline.

## What it does

| Stage | How |
|---|---|
| **Discover** | Playwright scrapers for Finn.no, NAV, Karrierestart, Jobbnorge + company career pages (incremental, deduped) |
| **Enrich** | BRREG company data (org number, employees, NACE) + website contact extraction |
| **Prospect** | Snov.io domain prospects, email finder, verification (valid/invalid/risky) |
| **Draft** | Template + Claude Haiku AI-personalized openers with A/B variants |
| **Outreach** | Snov.io campaigns + direct Resend sends + LinkedIn copy-ready messages |
| **Follow-up** | 3-step sequences on no-open, smart send-time scheduling (Tue–Thu 09:00–11:00 CET) |
| **Track** | Resend webhooks (opens/clicks/bounces), 7-stage CRM kanban, intent scoring 0–100 |

## Quick start

```bash
pip install -r requirements.txt
python -m playwright install chromium   # scraper browser (once)
cp .env.example .env                    # then fill in API keys
python main.py --status                 # verifies setup, auto-creates DB
python main.py                          # dashboard at http://127.0.0.1:5000
```

## Commands

```bash
python main.py                      # web dashboard + daily scheduler (default)
python main.py --now                 # one pipeline run now, then exit
python main.py --now --sources finn  # specific source(s): finn nav karrierestart jobbnorge careers
python main.py --status              # DB stats + Snov.io balance
python main.py --cli                 # terminal scheduler, no web UI
python main.py --host 0.0.0.0 --port 8080
```

## Configuration (`.env` — see `.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `FINN_KEYWORDS` | `seafood,aquaculture,sjømat` | comma-separated search keywords |
| `RUN_TIME` / `SEND_TIME` | `09:30` / `08:30` UTC | daily pipeline / send-job times |
| `PIPELINE_WORKERS` | `1` | parallel posting workers (`2`–`4` with Snov credits) |
| `DOMAIN_TIMEOUT_SEC` | `300` | max seconds per company domain |
| `CAREERS_MAX_DOMAINS` | `30` | known domains revisited per run by the careers source |
| `SNOV_MIN_CREDITS` | `0` | abort run below this balance (`0` = only when empty) |
| `SNOV_LOW_WATER_CREDITS` | `200` | warn (+ webhook) when balance drops below this |
| `SNOV_CLIENT_ID` / `SNOV_CLIENT_SECRET` | — | enrichment (required for prospects) |
| `SNOV_LIST_ID` | auto-created | Snov campaign list |
| `RESEND_API_KEY` | — | direct email sending |
| `FROM_EMAIL` / `FROM_NAME` | `fredrik.hansen@sperton.com` | sender identity |
| `FOLLOWUP_AUTO_SEND` | `false` | `true` = follow-ups pre-approved AND auto-sent; `false` (safe) = drafts await review |
| `FOLLOWUP_MIN_DAYS` / `FOLLOWUP_MAX_STEP` | `3` / `3` | follow-up timing and depth |
| `ANTHROPIC_API_KEY` | — | AI openers (falls back to templates) |
| `FLASK_SECRET` | ephemeral + warning | set a real value in production |
| `DASHBOARD_USER` / `DASHBOARD_PASS` | unset (open) | basic-auth login for the dashboard |
| `LOG_LEVEL` | `INFO` | logging verbosity |
| `LOG_FORMAT` | `pretty` | `pretty` (colored) or `json` (one object per line, for aggregation) |
| `LEADS_DB_PATH` | `./leads.db` | override the SQLite file location |

Central defaults and validation live in `src/config.py`.

## Safety rails (on by default)

- Follow-ups are created as **drafts awaiting approval** unless `FOLLOWUP_AUTO_SEND=true`.
- `send_email_direct` refuses drafts that aren't `approved` **and** refuses already-sent drafts (double-send guard).
- **Suppression list**: bounces and spam complaints (via Resend webhooks) permanently
  exclude addresses from both send paths; scheduled-for dates are honored by both.
- Resend retries only transport errors and rate limits — never API rejections
  (a 5xx may already have sent).
- All secrets come from the environment — no committed fallbacks.

## Testing

```bash
pytest tests/ -v                        # full suite (185 tests)
pytest tests/test_hardening.py -v       # security/safety regression tests
pytest tests/test_pipeline_run.py -v    # mocked end-to-end pipeline runs
ruff check src tests                    # lint (enforced in CI)
ruff format --check src tests           # formatting
```

Test scope, asyncio mode, and lint rules live in `pyproject.toml`.
`manual/` holds live-API debug scripts (real sites/credits, never in CI).

## Project layout

```
main.py                 multi-mode CLI (web / now / status / cli)
src/
  config.py             central settings + validation
  pipeline/             orchestration (scrape → enrich → verify → draft → export)
  scraper/              finn / nav / karrierestart / jobbnorge + website + browser_manager
  snov/                 Snov.io client (OAuth2, rate-limited)
  brreg/                Norwegian Business Register client
  database/db.py        SQLite schema, migrations, queries
  emails/               templates, AI drafter, LinkedIn templates, follow-up templates
  outreach/             Snov sender, Resend sender, follow-ups, smart scheduler
  export/               CSV / Excel / PDF exporters
  scheduler/            daily runner
  web/                  Flask dashboard (routes, templates, webhooks)
  logger.py             colored console + rotating file logging
tests/                  pytest suite
```

## Dashboard routes

`/` dashboard · `/postings` · `/prospects` (+`/profile`) · `/campaigns`
(+`/ab-tests`, `/linkedin`) · `/crm` kanban · `/settings` (pipeline controls,
keywords, exports) · `/webhooks/resend` (Resend events endpoint) ·
`/healthz` (unauthenticated liveness probe: process + DB counts)

## Docs

- `CLAUDE.md` — agent working guide for this repo
- `ROADMAP.md` — living roadmap: assessment, completed work, highest-value next steps
- `docs/archive/` — historical docs from the retired ERA track (not this project)
- `FILES_MANIFEST.txt` — file inventory (may lag; treat code as truth)
