"""
Run the leads pipeline in dry or live mode and emit a JSON summary.
This script is intended to be invoked by the OpenClaw cron agent.

Usage:
  .venv\Scripts\python.exe scripts\oc_run_pipeline.py --dry --top 5
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from src.database import db
from src.pipeline.lead_pipeline import LeadPipeline
from src.export.csv_exporter import export_prospects_csv


def make_fake_snov():
    """Return a fake Snov client that avoids network/credit usage in dry-run."""
    class FakeSnov:
        def get_user_lists(self):
            return []
        def create_list(self, name):
            return None
        def get_domain_email_count(self, domain):
            return 0
        def get_prospects_by_domain(self, domain, positions=None):
            return []
        def verify_email(self, email):
            # Don't call Snov verification in dry-run
            return "unknown"
        def find_domain_by_company_name(self, name):
            return None
        def add_prospect_to_list(self, list_id, prospect):
            return False
        def find_email_by_name_domain(self, first, last, domain):
            return {}
    return FakeSnov()


def main(dry: bool = True, top: int = 5):
    db.init_db()

    # Instantiate pipeline
    if dry:
        # Provide dummy SNOV creds so the real SnovClient can be constructed without raising,
        # then we immediately replace it with a fake client to avoid network/credit usage.
        os.environ.setdefault('SNOV_CLIENT_ID', 'DRY_RUN')
        os.environ.setdefault('SNOV_CLIENT_SECRET', 'DRY_RUN')

    pipeline = LeadPipeline(snov_list_id=os.getenv('SNOV_LIST_ID') or None)

    if dry:
        # Replace Snov client with a fake no-op to avoid using credits
        pipeline.snov = make_fake_snov()

    keywords = [k.strip() for k in os.getenv('FINN_KEYWORDS', 'seafood').split(',') if k.strip()]

    started = datetime.now(timezone.utc).isoformat()
    try:
        stats = pipeline.run(keywords)
        status = 'completed'
    except Exception as exc:
        stats = {'errors': 1, 'error_message': str(exc)}
        status = 'failed'

    # Ensure we have an export CSV and top prospects
    csv_path = export_prospects_csv()

    top_prospects, total = db.get_prospects_filtered(limit=top)

    finished = datetime.now(timezone.utc).isoformat()

    summary = {
        'started_at': started,
        'finished_at': finished,
        'status': status,
        'stats': stats,
        'csv_path': csv_path,
        'top_prospects': top_prospects,
    }

    # Save summary to uploads/
    uploads = PROJECT_ROOT / 'uploads'
    uploads.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out_file = uploads / f'pipeline_run_{ts}.json'
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    # Print to stdout for agents
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry', action='store_true', default=False, help='Run in dry-run mode (no Snov adds)')
    parser.add_argument('--top', type=int, default=5, help='Number of top prospects to include')
    parser.add_argument('--quick', action='store_true', default=False, help='Quick mode: skip scraping and pipeline run; only export & summarize DB')
    args = parser.parse_args()
    if args.quick:
        # Quick summary without running the full pipeline
        db.init_db()
        csv_path = export_prospects_csv()
        top_prospects, total = db.get_prospects_filtered(limit=args.top)
        now = datetime.now(timezone.utc).isoformat()
        summary = {
            'started_at': now,
            'finished_at': now,
            'status': 'quick-summary',
            'stats': db.get_dashboard_stats(),
            'csv_path': csv_path,
            'top_prospects': top_prospects,
        }
        uploads = PROJECT_ROOT / 'uploads'
        uploads.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        out_file = uploads / f'pipeline_run_{ts}.json'
        out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False))
    else:
        main(dry=args.dry, top=args.top)
