"""
Database migration script.
Migrates from old schema (finn_id) to new schema (source, external_id, org_number).
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

DB_PATH = Path(__file__).parent / "leads.db"


def migrate():
    """Run database migrations."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    logger.info("Starting database migration...")

    # Check if migration is needed
    cursor.execute("PRAGMA table_info(job_postings)")
    columns = {row[1] for row in cursor.fetchall()}

    if "external_id" in columns:
        logger.info("Database already migrated. Skipping.")
        conn.close()
        return

    logger.info("Migrating job_postings table...")

    # Step 1: Create new table with updated schema
    cursor.executescript("""
        CREATE TABLE job_postings_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT DEFAULT 'finn',
            external_id     TEXT NOT NULL,
            title           TEXT,
            company_name    TEXT,
            company_domain  TEXT,
            org_number      TEXT,
            location        TEXT,
            url             TEXT,
            keyword_matched TEXT,
            published_at    TEXT,
            scraped_at      TEXT NOT NULL,
            UNIQUE(source, external_id)
        );

        INSERT INTO job_postings_new
            (id, source, external_id, title, company_name, company_domain,
             location, url, keyword_matched, published_at, scraped_at)
        SELECT
            id, 'finn' as source, finn_id as external_id, title, company_name, company_domain,
            location, url, keyword_matched, published_at, scraped_at
        FROM job_postings;

        DROP TABLE job_postings;

        ALTER TABLE job_postings_new RENAME TO job_postings;
    """)

    logger.info("Creating new tables...")

    # Step 2: Create new tables (companies, company_roles)
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            org_number      TEXT UNIQUE NOT NULL,
            name            TEXT NOT NULL,
            website         TEXT,
            address         TEXT,
            postal_code     TEXT,
            city            TEXT,
            employee_count  INTEGER,
            nace_code       TEXT,
            nace_description TEXT,
            legal_form      TEXT,
            source          TEXT DEFAULT 'brreg',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS company_roles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id      INTEGER REFERENCES companies(id),
            org_number      TEXT NOT NULL,
            person_name     TEXT NOT NULL,
            role_code       TEXT NOT NULL,
            role_description TEXT,
            birth_date      TEXT,
            created_at      TEXT NOT NULL,
            UNIQUE(org_number, person_name, role_code)
        );
    """)

    logger.info("Recreating indexes...")

    # Step 3: Recreate indexes
    cursor.executescript("""
        CREATE INDEX IF NOT EXISTS idx_job_postings_external_id
            ON job_postings(external_id);
        CREATE INDEX IF NOT EXISTS idx_job_postings_source
            ON job_postings(source);
        CREATE INDEX IF NOT EXISTS idx_job_postings_org_number
            ON job_postings(org_number);
        CREATE INDEX IF NOT EXISTS idx_job_postings_company
            ON job_postings(company_name);
        CREATE INDEX IF NOT EXISTS idx_companies_org_number
            ON companies(org_number);
        CREATE INDEX IF NOT EXISTS idx_companies_nace
            ON companies(nace_code);
        CREATE INDEX IF NOT EXISTS idx_company_roles_org
            ON company_roles(org_number);
        CREATE INDEX IF NOT EXISTS idx_company_roles_company
            ON company_roles(company_id);
    """)

    conn.commit()
    conn.close()

    logger.info("Migration complete!")
    logger.info("job_postings: finn_id -> (source='finn', external_id)")
    logger.info("Added tables: companies, company_roles")


if __name__ == "__main__":
    migrate()
