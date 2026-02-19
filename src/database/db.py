"""
Database module — SQLite for local dev, PostgreSQL-ready for VPS migration.
Tracks all prospects, job postings, outreach status, email drafts, and pipeline runs.
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "leads.db"


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Apply incremental migrations to existing databases.
    Each ALTER TABLE is wrapped so it's safe to run multiple times.
    """
    migrations = [
        # v2: add source + external_id + org_number to job_postings
        "ALTER TABLE job_postings ADD COLUMN source TEXT DEFAULT 'finn'",
        "ALTER TABLE job_postings ADD COLUMN external_id TEXT",
        "ALTER TABLE job_postings ADD COLUMN org_number TEXT",
        # v2: back-fill external_id from finn_id where blank
        "UPDATE job_postings SET external_id = finn_id WHERE external_id IS NULL AND finn_id IS NOT NULL",
        # v3: ERA Group PDF extraction tables
        "ALTER TABLE era_pdf_uploads ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE era_pdf_uploads ADD COLUMN error_message TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except Exception:
            pass  # column already exists or table doesn't have finn_id — skip


def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        # Run schema migrations first so new indexes don't fail
        _migrate(conn)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS job_postings (
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

            CREATE TABLE IF NOT EXISTS prospects (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_posting_id  INTEGER REFERENCES job_postings(id),
                first_name      TEXT,
                last_name       TEXT,
                full_name       TEXT,
                email           TEXT UNIQUE,
                email_status    TEXT,
                position        TEXT,
                company_name    TEXT,
                company_domain  TEXT,
                linkedin_url    TEXT,
                snov_prospect_id TEXT,
                snov_list_id    TEXT,
                created_at      TEXT NOT NULL,
                enriched_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS outreach_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id     INTEGER REFERENCES prospects(id),
                campaign_id     TEXT,
                status          TEXT,
                sent_at         TEXT,
                opened_at       TEXT,
                replied_at      TEXT,
                notes           TEXT
            );

            CREATE TABLE IF NOT EXISTS email_drafts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id     INTEGER NOT NULL REFERENCES prospects(id),
                job_posting_id  INTEGER REFERENCES job_postings(id),
                template_name   TEXT NOT NULL,
                subject         TEXT NOT NULL,
                body            TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'draft',
                created_at      TEXT NOT NULL,
                approved_at     TEXT,
                sent_at         TEXT,
                opened_at       TEXT,
                replied_at      TEXT,
                notes           TEXT
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                status          TEXT NOT NULL DEFAULT 'running',
                postings_scraped    INTEGER DEFAULT 0,
                postings_new        INTEGER DEFAULT 0,
                domains_resolved    INTEGER DEFAULT 0,
                prospects_found     INTEGER DEFAULT 0,
                emails_found        INTEGER DEFAULT 0,
                emails_verified     INTEGER DEFAULT 0,
                prospects_added     INTEGER DEFAULT 0,
                drafts_created      INTEGER DEFAULT 0,
                csv_path            TEXT,
                errors              INTEGER DEFAULT 0,
                error_message       TEXT
            );

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

            CREATE INDEX IF NOT EXISTS idx_prospects_email
                ON prospects(email);
            CREATE INDEX IF NOT EXISTS idx_job_postings_external_id
                ON job_postings(external_id);
            CREATE INDEX IF NOT EXISTS idx_job_postings_source
                ON job_postings(source);
            CREATE INDEX IF NOT EXISTS idx_job_postings_org_number
                ON job_postings(org_number);
            CREATE INDEX IF NOT EXISTS idx_job_postings_company
                ON job_postings(company_name);
            CREATE INDEX IF NOT EXISTS idx_email_drafts_prospect
                ON email_drafts(prospect_id);
            CREATE INDEX IF NOT EXISTS idx_email_drafts_status
                ON email_drafts(status);
            CREATE INDEX IF NOT EXISTS idx_email_drafts_job_posting
                ON email_drafts(job_posting_id);
            CREATE INDEX IF NOT EXISTS idx_companies_org_number
                ON companies(org_number);
            CREATE INDEX IF NOT EXISTS idx_companies_nace
                ON companies(nace_code);
            CREATE INDEX IF NOT EXISTS idx_company_roles_org
                ON company_roles(org_number);
            CREATE INDEX IF NOT EXISTS idx_company_roles_company
                ON company_roles(company_id);

            CREATE TABLE IF NOT EXISTS keywords (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword     TEXT UNIQUE NOT NULL,
                active      INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS era_pdf_uploads (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                filename        TEXT NOT NULL,
                file_size       INTEGER,
                upload_date     TEXT NOT NULL,
                status          TEXT DEFAULT 'pending',
                error_message   TEXT,
                processing_time INTEGER,
                UNIQUE(filename, upload_date)
            );

            CREATE TABLE IF NOT EXISTS era_extractions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_id          INTEGER NOT NULL REFERENCES era_pdf_uploads(id),
                extraction_type TEXT NOT NULL,
                extracted_data  TEXT NOT NULL,
                confidence_score REAL DEFAULT 0.0,
                extraction_date TEXT NOT NULL,
                page_number     INTEGER,
                field_count     INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS era_extraction_templates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                template_name   TEXT UNIQUE NOT NULL,
                pattern_type    TEXT NOT NULL,
                field_mapping   TEXT,
                created_date    TEXT NOT NULL,
                updated_date    TEXT,
                active          INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS era_corrections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_id   INTEGER NOT NULL REFERENCES era_extractions(id),
                field_name      TEXT NOT NULL,
                original_value  TEXT,
                corrected_value TEXT NOT NULL,
                correction_date TEXT NOT NULL,
                used_for_training INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_era_uploads_status
                ON era_pdf_uploads(status);
            CREATE INDEX IF NOT EXISTS idx_era_extractions_pdf
                ON era_extractions(pdf_id);
            CREATE INDEX IF NOT EXISTS idx_era_extractions_type
                ON era_extractions(extraction_type);
            CREATE INDEX IF NOT EXISTS idx_era_corrections_extraction
                ON era_corrections(extraction_id);
        """)
    logger.info("Database initialised at %s", DB_PATH)


# ------------------------------------------------------------------
# Job postings
# ------------------------------------------------------------------

def insert_job_posting(data: dict) -> Optional[int]:
    """
    Insert a job posting. Returns new row id, or None if (source, external_id) already exists.

    Args:
        data: Dict with keys:
            - external_id (required) - external ID from job board
            - source (optional) - job board name (default: 'finn')
            - finn_id (backward compat) - maps to external_id if external_id not provided
            - title, company_name, company_domain, org_number
            - location, url, keyword_matched, published_at, scraped_at
    """
    # Backward compatibility: finn_id -> external_id
    if "finn_id" in data and "external_id" not in data:
        data["external_id"] = data["finn_id"]

    sql = """
        INSERT OR IGNORE INTO job_postings
            (source, external_id, title, company_name, company_domain, org_number,
             location, url, keyword_matched, published_at, scraped_at)
        VALUES
            (:source, :external_id, :title, :company_name, :company_domain, :org_number,
             :location, :url, :keyword_matched, :published_at, :scraped_at)
    """
    data.setdefault("source", "finn")
    data.setdefault("org_number", None)
    data.setdefault("company_domain", None)
    data.setdefault("title", None)
    data.setdefault("company_name", None)
    data.setdefault("location", None)
    data.setdefault("url", None)
    data.setdefault("keyword_matched", None)
    data.setdefault("published_at", None)
    data.setdefault("scraped_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        if cur.lastrowid and cur.rowcount:
            logger.debug(
                "Inserted job posting source=%s external_id=%s",
                data.get("source"),
                data.get("external_id"),
            )
            return cur.lastrowid
    return None


def get_job_postings(
    search: str = None,
    keyword: str = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return paginated job postings with optional search/filter. Returns (rows, total)."""
    conditions = []
    params = []

    if search:
        conditions.append("(title LIKE ? OR company_name LIKE ? OR location LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    if keyword:
        conditions.append("keyword_matched = ?")
        params.append(keyword)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM job_postings {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM job_postings {where} ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return [dict(r) for r in rows], total


def get_all_keywords() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT keyword_matched FROM job_postings WHERE keyword_matched != '' ORDER BY keyword_matched"
        ).fetchall()
    return [r[0] for r in rows if r[0]]


def get_postings_for_export() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM job_postings ORDER BY scraped_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Prospects
# ------------------------------------------------------------------

def insert_prospect(data: dict) -> Optional[int]:
    """Insert a prospect. Returns new row id, or None if email already exists."""
    sql = """
        INSERT OR IGNORE INTO prospects
            (job_posting_id, first_name, last_name, full_name,
             email, email_status, position, company_name,
             company_domain, linkedin_url, snov_prospect_id,
             snov_list_id, created_at)
        VALUES
            (:job_posting_id, :first_name, :last_name, :full_name,
             :email, :email_status, :position, :company_name,
             :company_domain, :linkedin_url, :snov_prospect_id,
             :snov_list_id, :created_at)
    """
    data.setdefault("created_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        if cur.lastrowid and cur.rowcount:
            logger.debug("Inserted prospect email=%s", data.get("email"))
            return cur.lastrowid
    return None


def email_exists(email: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM prospects WHERE email = ?", (email,)
        ).fetchone()
        return row is not None


def get_prospect_by_email(email: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM prospects WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None


def get_prospect_by_id(prospect_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM prospects WHERE id = ?", (prospect_id,)
        ).fetchone()
        return dict(row) if row else None


def get_prospects_filtered(
    search: str = None,
    email_status: str = None,
    company: str = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return paginated prospects with optional filters. Returns (rows, total)."""
    conditions = []
    params = []

    if search:
        conditions.append(
            "(full_name LIKE ? OR email LIKE ? OR company_name LIKE ? OR position LIKE ?)"
        )
        params.extend([f"%{search}%"] * 4)
    if email_status:
        conditions.append("email_status = ?")
        params.append(email_status)
    if company:
        conditions.append("company_name LIKE ?")
        params.append(f"%{company}%")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM prospects {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT p.*, jp.title as job_title,
                       jp.external_id as finn_id
                FROM prospects p
                LEFT JOIN job_postings jp ON p.job_posting_id = jp.id
                {where.replace('full_name', 'p.full_name').replace('email LIKE', 'p.email LIKE').replace('company_name', 'p.company_name').replace('email_status', 'p.email_status').replace('position', 'p.position')}
                ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

    return [dict(r) for r in rows], total


def get_prospects_for_export() -> list[dict]:
    """Return all prospects joined with job postings for CSV export."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                p.created_at as date,
                p.company_name, p.company_domain,
                p.full_name as contact_name, p.email,
                p.position as title,
                jp.title as job_posting_title,
                jp.keyword_matched as keyword,
                p.email_status,
                COALESCE(
                    (SELECT ed.status FROM email_drafts ed
                     WHERE ed.prospect_id = p.id
                     ORDER BY ed.created_at DESC LIMIT 1),
                    'no_draft'
                ) as outreach_status
            FROM prospects p
            LEFT JOIN job_postings jp ON p.job_posting_id = jp.id
            ORDER BY p.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Outreach log
# ------------------------------------------------------------------

def log_outreach(data: dict) -> None:
    sql = """
        INSERT INTO outreach_log
            (prospect_id, campaign_id, status, sent_at, notes)
        VALUES
            (:prospect_id, :campaign_id, :status, :sent_at, :notes)
    """
    data.setdefault("sent_at", _now())
    with get_connection() as conn:
        conn.execute(sql, data)


# ------------------------------------------------------------------
# Email drafts
# ------------------------------------------------------------------

def insert_email_draft(data: dict) -> Optional[int]:
    sql = """
        INSERT INTO email_drafts
            (prospect_id, job_posting_id, template_name,
             subject, body, status, created_at)
        VALUES
            (:prospect_id, :job_posting_id, :template_name,
             :subject, :body, :status, :created_at)
    """
    data.setdefault("status", "draft")
    data.setdefault("created_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        return cur.lastrowid if cur.lastrowid else None


def get_email_drafts(
    status: str = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return paginated email drafts with prospect and posting info."""
    conditions = []
    params = []

    if status:
        conditions.append("ed.status = ?")
        params.append(status)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM email_drafts ed {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT ed.*,
                       p.full_name as prospect_name, p.email as prospect_email,
                       p.company_name, p.position as prospect_title,
                       jp.title as job_title, jp.location as job_location
                FROM email_drafts ed
                JOIN prospects p ON ed.prospect_id = p.id
                LEFT JOIN job_postings jp ON ed.job_posting_id = jp.id
                {where}
                ORDER BY ed.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

    return [dict(r) for r in rows], total


def get_email_draft_by_id(draft_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT ed.*,
                      p.full_name as prospect_name, p.email as prospect_email,
                      p.company_name, p.company_domain,
                      jp.title as job_title, jp.location as job_location, jp.url as job_url
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               LEFT JOIN job_postings jp ON ed.job_posting_id = jp.id
               WHERE ed.id = ?""",
            (draft_id,),
        ).fetchone()
        return dict(row) if row else None


def update_email_draft(draft_id: int, data: dict) -> None:
    """Update fields on an email draft."""
    sets = []
    params = []
    for key, val in data.items():
        sets.append(f"{key} = ?")
        params.append(val)
    params.append(draft_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE email_drafts SET {', '.join(sets)} WHERE id = ?", params
        )


def draft_exists_for_prospect(prospect_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM email_drafts WHERE prospect_id = ?", (prospect_id,)
        ).fetchone()
        return row is not None


# ------------------------------------------------------------------
# Pipeline runs
# ------------------------------------------------------------------

def insert_pipeline_run(data: dict = None) -> int:
    data = data or {}
    data.setdefault("started_at", _now())
    data.setdefault("status", "running")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO pipeline_runs (started_at, status) VALUES (:started_at, :status)",
            data,
        )
        return cur.lastrowid


def update_pipeline_run(run_id: int, data: dict) -> None:
    sets = []
    params = []
    for key, val in data.items():
        sets.append(f"{key} = ?")
        params.append(val)
    params.append(run_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = ?", params
        )


def get_recent_pipeline_runs(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Dashboard aggregation
# ------------------------------------------------------------------

def get_dashboard_stats() -> dict:
    with get_connection() as conn:
        total_postings = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
        total_prospects = conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0]
        verified_emails = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE email_status = 'valid'"
        ).fetchone()[0]
        total_drafts = conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0]
        drafts_sent = conn.execute(
            "SELECT COUNT(*) FROM email_drafts WHERE status = 'sent'"
        ).fetchone()[0]
        drafts_replied = conn.execute(
            "SELECT COUNT(*) FROM email_drafts WHERE status = 'replied'"
        ).fetchone()[0]

        today = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        new_postings_today = conn.execute(
            "SELECT COUNT(*) FROM job_postings WHERE scraped_at LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        new_prospects_today = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE created_at LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]

    response_rate = (drafts_replied / drafts_sent * 100) if drafts_sent > 0 else 0.0

    return {
        "total_postings": total_postings,
        "total_prospects": total_prospects,
        "verified_emails": verified_emails,
        "total_drafts": total_drafts,
        "drafts_sent": drafts_sent,
        "drafts_replied": drafts_replied,
        "response_rate": round(response_rate, 1),
        "new_postings_today": new_postings_today,
        "new_prospects_today": new_prospects_today,
    }


def get_recent_activity(limit: int = 20) -> list[dict]:
    """Return recent activity across all tables, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT 'posting' as type, company_name as title,
                       'Scraped: ' || title as description,
                       scraped_at as timestamp
                FROM job_postings
                ORDER BY scraped_at DESC LIMIT 10
            )
            UNION ALL
            SELECT * FROM (
                SELECT 'prospect' as type, full_name as title,
                       email || ' at ' || company_name as description,
                       created_at as timestamp
                FROM prospects
                ORDER BY created_at DESC LIMIT 10
            )
            UNION ALL
            SELECT * FROM (
                SELECT 'draft' as type, subject as title,
                       'Status: ' || status as description,
                       created_at as timestamp
                FROM email_drafts
                ORDER BY created_at DESC LIMIT 10
            )
            ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_postings_by_day(days: int = 30) -> list[dict]:
    """Daily count of postings over last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT DATE(scraped_at) as day, COUNT(*) as count
               FROM job_postings
               WHERE scraped_at >= DATE('now', ?)
               GROUP BY DATE(scraped_at)
               ORDER BY day""",
            (f"-{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]


def get_prospects_by_day(days: int = 30) -> list[dict]:
    """Daily count of prospects over last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT DATE(created_at) as day, COUNT(*) as count
               FROM prospects
               WHERE created_at >= DATE('now', ?)
               GROUP BY DATE(created_at)
               ORDER BY day""",
            (f"-{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]


def get_job_posting_by_id(posting_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM job_postings WHERE id = ?", (posting_id,)
        ).fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------------
# Companies (BRREG data)
# ------------------------------------------------------------------

def insert_company(data: dict) -> Optional[int]:
    """
    Insert a company from BRREG. Returns new row id, or None if org_number exists.

    Args:
        data: Dict with keys:
            - org_number (required)
            - name (required)
            - website, address, postal_code, city
            - employee_count, nace_code, nace_description
            - legal_form, source
    """
    sql = """
        INSERT OR IGNORE INTO companies
            (org_number, name, website, address, postal_code, city,
             employee_count, nace_code, nace_description, legal_form,
             source, created_at, updated_at)
        VALUES
            (:org_number, :name, :website, :address, :postal_code, :city,
             :employee_count, :nace_code, :nace_description, :legal_form,
             :source, :created_at, :updated_at)
    """
    data.setdefault("source", "brreg")
    data.setdefault("created_at", _now())
    data.setdefault("updated_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        if cur.lastrowid and cur.rowcount:
            logger.debug("Inserted company org=%s name=%s", data["org_number"], data["name"])
            return cur.lastrowid
    return None


def get_company_by_org_number(org_number: str) -> Optional[dict]:
    """Get company by organization number."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE org_number = ?", (org_number,)
        ).fetchone()
        return dict(row) if row else None


def company_exists(org_number: str) -> bool:
    """Check if company already exists in database."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM companies WHERE org_number = ?", (org_number,)
        ).fetchone()
        return row is not None


def insert_company_role(data: dict) -> Optional[int]:
    """
    Insert a company role (board member, CEO, etc.).

    Args:
        data: Dict with keys:
            - company_id or org_number (required)
            - person_name (required)
            - role_code (required)
            - role_description
            - birth_date
    """
    sql = """
        INSERT OR IGNORE INTO company_roles
            (company_id, org_number, person_name, role_code,
             role_description, birth_date, created_at)
        VALUES
            (:company_id, :org_number, :person_name, :role_code,
             :role_description, :birth_date, :created_at)
    """
    data.setdefault("created_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        if cur.lastrowid and cur.rowcount:
            logger.debug(
                "Inserted role: %s as %s for org %s",
                data["person_name"],
                data["role_code"],
                data.get("org_number", ""),
            )
            return cur.lastrowid
    return None


def get_company_roles(org_number: str) -> list[dict]:
    """Get all roles (board members, management) for a company."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM company_roles
               WHERE org_number = ?
               ORDER BY
                   CASE role_code
                       WHEN 'DAGL' THEN 1
                       WHEN 'LEDE' THEN 2
                       WHEN 'NEST' THEN 3
                       WHEN 'MEDL' THEN 4
                       ELSE 5
                   END""",
            (org_number,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_companies_by_nace(nace_code: str, limit: int = 100) -> list[dict]:
    """
    Get companies by NACE code (supports prefix matching).
    E.g. nace_code='03.2' will match 03.2, 03.21, 03.211, etc.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM companies
               WHERE nace_code LIKE ?
               ORDER BY employee_count DESC
               LIMIT ?""",
            (f"{nace_code}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Keywords
# ------------------------------------------------------------------

def get_keywords(active_only: bool = True) -> list[dict]:
    """Return all keywords (or only active ones)."""
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM keywords WHERE active = 1 ORDER BY keyword"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM keywords ORDER BY keyword"
            ).fetchall()
    return [dict(r) for r in rows]


def get_keyword_list() -> list[str]:
    """Return a plain list of active keyword strings."""
    return [kw["keyword"] for kw in get_keywords(active_only=True)]


def add_keyword(keyword: str) -> Optional[int]:
    """Add a new keyword. Returns id or None if it already exists."""
    keyword = keyword.strip().lower()
    if not keyword:
        return None
    with get_connection() as conn:
        # Re-activate if it exists but was deactivated
        existing = conn.execute(
            "SELECT id, active FROM keywords WHERE keyword = ?", (keyword,)
        ).fetchone()
        if existing:
            if not existing["active"]:
                conn.execute(
                    "UPDATE keywords SET active = 1 WHERE id = ?", (existing["id"],)
                )
                logger.info("Re-activated keyword: %s", keyword)
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO keywords (keyword, active, created_at) VALUES (?, 1, ?)",
            (keyword, _now()),
        )
        logger.info("Added keyword: %s", keyword)
        return cur.lastrowid


def remove_keyword(keyword_id: int) -> bool:
    """Delete a keyword by id. Returns True if deleted."""
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Removed keyword id=%d", keyword_id)
        return deleted


def seed_keywords_from_env(env_keywords: list[str]) -> int:
    """Seed the keywords table from .env if the table is empty. Returns count added."""
    existing = get_keywords(active_only=False)
    if existing:
        return 0
    count = 0
    for kw in env_keywords:
        kw = kw.strip()
        if kw and add_keyword(kw):
            count += 1
    logger.info("Seeded %d keywords from .env", count)


# ------------------------------------------------------------------
# ERA Group PDF Extraction
# ------------------------------------------------------------------

def insert_pdf_upload(filename: str, file_size: int, status: str = "pending") -> Optional[int]:
    """Insert a new PDF upload record. Returns upload_id or None if duplicate."""
    sql = """
        INSERT OR IGNORE INTO era_pdf_uploads (filename, file_size, upload_date, status)
        VALUES (?, ?, ?, ?)
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (filename, file_size, _now(), status))
        if cur.lastrowid and cur.rowcount:
            logger.info("Inserted PDF upload: %s (size=%d bytes)", filename, file_size)
            return cur.lastrowid
    return None


def update_pdf_status(pdf_id: int, status: str, error_message: str = None, processing_time: int = None) -> bool:
    """Update PDF upload status. Returns True if updated."""
    sql = """
        UPDATE era_pdf_uploads
        SET status = ?, error_message = ?, processing_time = ?
        WHERE id = ?
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (status, error_message, processing_time, pdf_id))
        updated = cur.rowcount > 0
        if updated:
            logger.info("Updated PDF %d status to %s", pdf_id, status)
        return updated


def insert_extraction(pdf_id: int, extraction_type: str, extracted_data: str, confidence_score: float = 0.0, page_number: int = None, field_count: int = 0) -> Optional[int]:
    """Insert extracted data. Returns extraction_id or None."""
    sql = """
        INSERT INTO era_extractions (pdf_id, extraction_type, extracted_data, confidence_score, extraction_date, page_number, field_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (pdf_id, extraction_type, extracted_data, confidence_score, _now(), page_number, field_count))
        if cur.lastrowid:
            logger.info("Inserted extraction id=%d from PDF id=%d", cur.lastrowid, pdf_id)
            return cur.lastrowid
    return None


def get_era_dashboard_stats() -> dict:
    """Get ERA Group dashboard statistics."""
    with get_connection() as conn:
        # Count uploads by status
        uploads = conn.execute("SELECT COUNT(*) as total FROM era_pdf_uploads").fetchone()
        completed = conn.execute("SELECT COUNT(*) as total FROM era_pdf_uploads WHERE status = 'completed'").fetchone()
        processing = conn.execute("SELECT COUNT(*) as total FROM era_pdf_uploads WHERE status = 'pending' OR status = 'processing'").fetchone()
        failed = conn.execute("SELECT COUNT(*) as total FROM era_pdf_uploads WHERE status = 'error'").fetchone()

        # Count extractions
        extractions = conn.execute("SELECT COUNT(*) as total FROM era_extractions").fetchone()

        # Average confidence
        avg_confidence = conn.execute("SELECT AVG(confidence_score) as avg FROM era_extractions").fetchone()

        # Avg processing time
        avg_time = conn.execute("SELECT AVG(processing_time) as avg FROM era_pdf_uploads WHERE processing_time IS NOT NULL").fetchone()

    return {
        "total_uploads": uploads[0] if uploads else 0,
        "completed_uploads": completed[0] if completed else 0,
        "processing_uploads": processing[0] if processing else 0,
        "failed_uploads": failed[0] if failed else 0,
        "total_extractions": extractions[0] if extractions else 0,
        "avg_confidence": round((avg_confidence[0] or 0) * 100, 1),
        "avg_processing_time": round(avg_time[0] or 0, 1),
    }


def get_all_extractions_for_export() -> list[dict]:
    """Get all extractions for CSV/Excel export."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                ee.id,
                eu.filename,
                eu.upload_date,
                ee.extraction_type,
                ee.extracted_data,
                ee.confidence_score,
                ee.extraction_date,
                ee.page_number,
                ee.field_count
            FROM era_extractions ee
            LEFT JOIN era_pdf_uploads eu ON ee.pdf_id = eu.id
            ORDER BY ee.extraction_date DESC
        """).fetchall()
    return [dict(row) for row in rows]


def get_pdf_uploads(status: str = None, limit: int = 50) -> list[dict]:
    """Get PDF uploads, optionally filtered by status."""
    query = "SELECT * FROM era_pdf_uploads"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY upload_date DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def log_correction(extraction_id: int, field_name: str, original_value: str, corrected_value: str) -> Optional[int]:
    """Log a user correction for model training. Returns correction_id."""
    sql = """
        INSERT INTO era_corrections (extraction_id, field_name, original_value, corrected_value, correction_date)
        VALUES (?, ?, ?, ?, ?)
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (extraction_id, field_name, original_value, corrected_value, _now()))
        if cur.lastrowid:
            logger.info("Logged correction for extraction %d field %s", extraction_id, field_name)
            return cur.lastrowid
    return None
    return count
