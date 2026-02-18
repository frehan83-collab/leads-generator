# Leads Generator

Automated lead generation tool for Sperton recruiting.
Crawls finn.no daily, enriches prospects via Snov.io, and adds them to outreach campaigns.

## Quick Start

### 1. Install Python
Download from https://www.python.org/downloads/ — tick "Add Python to PATH" during install.

### 2. Run Setup
Double-click `setup.bat` or run in terminal:
```
setup.bat
```

### 3. Configure .env
Open `.env` and fill in your Snov.io client secret:
```
SNOV_CLIENT_SECRET=your_secret_here
SNOV_LIST_ID=your_snov_list_id  (optional, auto-created if blank)
```

### 4. Run

| Command | What it does |
|---------|-------------|
| `python main.py --now` | Run pipeline immediately (test) |
| `python main.py --status` | Show DB stats + Snov balance |
| `python main.py` | Start scheduler (runs daily at 09:30) |

### 5. Run Tests
```
pytest tests/ -v
```

## Project Structure

```
leads_generator/
├── main.py                    # Entry point
├── .env                       # Config (never commit this)
├── requirements.txt
├── setup.bat                  # Windows setup script
├── src/
│   ├── scraper/
│   │   └── finn_scraper.py    # Playwright-based finn.no scraper
│   ├── snov/
│   │   └── client.py          # Full Snov.io API client
│   ├── database/
│   │   └── db.py              # SQLite database (PostgreSQL-ready)
│   ├── pipeline/
│   │   └── lead_pipeline.py   # Orchestrates the full pipeline
│   ├── scheduler/
│   │   └── runner.py          # Daily scheduler (09:30)
│   └── logger.py              # Coloured logging + file rotation
├── tests/
│   ├── test_scraper.py
│   ├── test_database.py
│   └── test_snov_client.py
└── logs/                      # Auto-created log files
```

## Pipeline Flow

```
finn.no scrape (keywords)
    ↓
New job postings → saved to DB
    ↓
Resolve company domain (Snov.io)
    ↓
Find prospects by domain + job title (Snov.io)
    ↓
Find + verify email (Snov.io)
    ↓
Skip if already contacted (DB dedup)
    ↓
Save prospect to DB
    ↓
Add to Snov.io campaign list → email outreach begins
```

## Keywords (configurable in .env)
```
FINN_KEYWORDS=seafood,aquaculture,sjømat,biologi
```

## VPS Migration
When ready to deploy to VPS:
1. Copy project to VPS
2. Run `setup.bat` equivalent on Linux
3. Replace SQLite with PostgreSQL (change `db.py` connection string)
4. Use `systemd` service instead of Windows Task Scheduler
