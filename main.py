"""
Entry points:

  python main.py           — start the web dashboard (localhost:5000) with background scheduler
  python main.py --web     — same as above (explicit flag)
  python main.py --now     — run the pipeline immediately (no web server)
  python main.py --status  — show DB stats and Snov account balance
  python main.py --cli     — start the legacy CLI scheduler (no web server)
"""

import argparse
import logging
import os

from dotenv import load_dotenv

from src.logger import setup_logging

load_dotenv()


def cmd_web(host: str = "127.0.0.1", port: int = 5000):
    from src.web.app import start_web
    start_web(host=host, port=port, with_scheduler=True)


def cmd_run_now(sources: list[str] = None):
    from src.pipeline.lead_pipeline import LeadPipeline
    keywords = [k.strip() for k in os.getenv("FINN_KEYWORDS", "seafood").split(",")]
    snov_list_id = os.getenv("SNOV_LIST_ID")

    # Default to both finn and nav if not specified
    if not sources:
        sources = ['finn', 'nav']

    print(f"\nRunning pipeline with sources: {', '.join(sources)}")
    print(f"Keywords: {', '.join(keywords)}\n")

    pipeline = LeadPipeline(snov_list_id=snov_list_id, sources=sources)
    stats = pipeline.run(keywords)
    print("\n--- Run complete ---")
    for k, v in stats.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for sub_k, sub_v in v.items():
                print(f"    {sub_k}: {sub_v}")
        else:
            print(f"  {k:<35} {v}")


def cmd_scheduler():
    from src.scheduler.runner import start_scheduler
    run_time = os.getenv("RUN_TIME", "09:30")
    start_scheduler(run_time=run_time)


def cmd_status():
    from src.database.db import get_connection, init_db
    from src.snov.client import SnovClient

    init_db()
    print("\n--- Database Stats ---")
    with get_connection() as conn:
        postings = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
        prospects = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
        verified = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE email_status = 'valid'"
        ).fetchone()[0]
        outreach = conn.execute("SELECT COUNT(*) FROM outreach_log").fetchone()[0]
        drafts = conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0]
        companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]

        # Per-source breakdown
        source_stats = conn.execute(
            "SELECT source, COUNT(*) FROM job_postings GROUP BY source"
        ).fetchall()

    print(f"  Job postings in DB:        {postings}")
    if source_stats:
        for source, count in source_stats:
            print(f"    - {source or 'unknown'}:".ljust(30) + str(count))
    print(f"  Prospects in DB:           {prospects}")
    print(f"  Verified emails:           {verified}")
    print(f"  Email drafts:              {drafts}")
    print(f"  Outreach log entries:      {outreach}")
    print(f"  Companies (BRREG):         {companies}")

    print("\n--- Snov.io Account ---")
    try:
        snov = SnovClient()
        balance = snov.get_balance()
        data = balance.get("data") or balance
        print(f"  Credits remaining:         {data.get('balance', 'N/A')}")
        print(f"  Recipients used this month:{data.get('recipients_used', 'N/A')}")
        print(f"  Limit resets in:           {data.get('limit_resets_in', 'N/A')} days")
        print(f"  Subscription expires in:   {data.get('expires_in', 'N/A')} days")
    except Exception as exc:
        print(f"  Could not fetch balance: {exc}")


if __name__ == "__main__":
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Sperton Leads Generator")
    parser.add_argument("--web", action="store_true", help="Start web dashboard (default)")
    parser.add_argument("--cli", action="store_true", help="Start CLI scheduler (no web)")
    parser.add_argument("--now", action="store_true", help="Run pipeline immediately")
    parser.add_argument("--status", action="store_true", help="Show status and account info")
    parser.add_argument("--sources", nargs="+", choices=["finn", "nav"], help="Sources to scrape (default: finn nav)")
    parser.add_argument("--host", default="127.0.0.1", help="Web server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Web server port (default: 5000)")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.now:
        cmd_run_now(sources=args.sources)
    elif args.cli:
        cmd_scheduler()
    else:
        # Default: web dashboard
        print(f"\n  Sperton Leads Dashboard")
        print(f"  Starting at http://{args.host}:{args.port}")
        print(f"  Press Ctrl+C to stop\n")
        cmd_web(host=args.host, port=args.port)
