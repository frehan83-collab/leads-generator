"""
Database module — SQLite for local dev, PostgreSQL-ready for VPS migration.
Tracks all prospects, job postings, outreach status, email drafts, and pipeline runs.
"""

import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(
    os.getenv("LEADS_DB_PATH", Path(__file__).parent.parent.parent / "leads.db")
)


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names for a table (empty set if missing)."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards in user search input (backslash is the escape char)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_contains(value: str) -> str:
    """Wrap escaped user input for a LIKE %...% match with explicit ESCAPE."""
    return f"%{_like_escape(value)}%"


# (table, column, ddl) — applied only when the table exists and lacks the column.
_MIGRATIONS: list[tuple[str, str, str]] = [
    # v2: add source + external_id + org_number to job_postings
    (
        "job_postings",
        "source",
        "ALTER TABLE job_postings ADD COLUMN source TEXT DEFAULT 'finn'",
    ),
    (
        "job_postings",
        "external_id",
        "ALTER TABLE job_postings ADD COLUMN external_id TEXT",
    ),
    (
        "job_postings",
        "org_number",
        "ALTER TABLE job_postings ADD COLUMN org_number TEXT",
    ),
    # v9: posting lifecycle (active/expired/unknown + last check)
    (
        "job_postings",
        "status",
        "ALTER TABLE job_postings ADD COLUMN status TEXT DEFAULT 'unknown'",
    ),
    (
        "job_postings",
        "last_checked_at",
        "ALTER TABLE job_postings ADD COLUMN last_checked_at TEXT",
    ),
    # v4: Resend webhook tracking (F1)
    ("email_drafts", "resend_id", "ALTER TABLE email_drafts ADD COLUMN resend_id TEXT"),
    (
        "email_drafts",
        "open_count",
        "ALTER TABLE email_drafts ADD COLUMN open_count INTEGER DEFAULT 0",
    ),
    (
        "email_drafts",
        "click_count",
        "ALTER TABLE email_drafts ADD COLUMN click_count INTEGER DEFAULT 0",
    ),
    # v5: Follow-up sequences (F3)
    (
        "email_drafts",
        "sequence_step",
        "ALTER TABLE email_drafts ADD COLUMN sequence_step INTEGER DEFAULT 1",
    ),
    (
        "email_drafts",
        "parent_draft_id",
        "ALTER TABLE email_drafts ADD COLUMN parent_draft_id INTEGER REFERENCES email_drafts(id)",
    ),
    # v6: AI variants (F5)
    (
        "email_drafts",
        "variant_of",
        "ALTER TABLE email_drafts ADD COLUMN variant_of INTEGER REFERENCES email_drafts(id)",
    ),
    (
        "email_drafts",
        "ai_context",
        "ALTER TABLE email_drafts ADD COLUMN ai_context TEXT",
    ),
    # v7: Intent signals (C3)
    (
        "companies",
        "intent_score",
        "ALTER TABLE companies ADD COLUMN intent_score INTEGER DEFAULT 0",
    ),
    (
        "companies",
        "intent_signals",
        "ALTER TABLE companies ADD COLUMN intent_signals TEXT",
    ),
    # v8: Smart scheduler (C5)
    (
        "email_drafts",
        "scheduled_for",
        "ALTER TABLE email_drafts ADD COLUMN scheduled_for TEXT",
    ),
    # v9: posting lifecycle is declared above (job_postings status/last_checked_at)
    # v10: pipeline run revalidation counters
    (
        "pipeline_runs",
        "postings_revalidated",
        "ALTER TABLE pipeline_runs ADD COLUMN postings_revalidated INTEGER DEFAULT 0",
    ),
    (
        "pipeline_runs",
        "postings_expired",
        "ALTER TABLE pipeline_runs ADD COLUMN postings_expired INTEGER DEFAULT 0",
    ),
]

# Columns callers are allowed to update dynamically (SQL-injection guard).
_UPDATABLE_COLUMNS: dict[str, frozenset[str]] = {
    "email_drafts": frozenset(
        {
            "template_name",
            "subject",
            "body",
            "status",
            "approved_at",
            "sent_at",
            "opened_at",
            "replied_at",
            "notes",
            "resend_id",
            "open_count",
            "click_count",
            "sequence_step",
            "parent_draft_id",
            "variant_of",
            "ai_context",
            "scheduled_for",
            "prospect_id",
            "job_posting_id",
        }
    ),
    "pipeline_runs": frozenset(
        {
            "finished_at",
            "status",
            "postings_scraped",
            "postings_new",
            "domains_resolved",
            "prospects_found",
            "emails_found",
            "emails_verified",
            "prospects_added",
            "drafts_created",
            "postings_revalidated",
            "postings_expired",
            "csv_path",
            "errors",
            "error_message",
        }
    ),
    "linkedin_messages": frozenset(
        {
            "message_type",
            "message_text",
            "status",
            "copied_at",
            "sent_at",
            "replied_at",
            "notes",
            "prospect_id",
            "draft_id",
        }
    ),
    "job_postings": frozenset(
        {
            "title",
            "company_name",
            "company_domain",
            "org_number",
            "location",
            "url",
            "keyword_matched",
            "published_at",
            "status",
            "last_checked_at",
        }
    ),
}


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Apply incremental migrations to existing databases.
    Each migration runs only when its table exists and lacks the column,
    so this is safe to run on every startup. Unexpected errors are logged
    loudly instead of being swallowed.
    """
    for table, column, ddl in _MIGRATIONS:
        cols = _table_columns(conn, table)
        if not cols:
            continue  # fresh DB: base schema (run next) already has it
        if column in cols:
            continue
        try:
            conn.execute(ddl)
            logger.info("Migration applied: %s.%s", table, column)
        except Exception:
            logger.exception("Migration FAILED: %s", ddl)
            raise

    # v2 back-fill: external_id from legacy finn_id where blank
    cols = _table_columns(conn, "job_postings")
    if cols and "external_id" in cols and "finn_id" in cols:
        conn.execute(
            "UPDATE job_postings SET external_id = finn_id "
            "WHERE external_id IS NULL AND finn_id IS NOT NULL"
        )


# Full DDL. CREATE TABLE statements must execute before _migrate(),
# and CREATE INDEX statements (several reference migrated columns) last.
# See init_db() which enforces that order via _split_schema().
_SCHEMA = """
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
                status          TEXT DEFAULT 'unknown',
                last_checked_at TEXT,
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
                postings_revalidated INTEGER DEFAULT 0,
                postings_expired    INTEGER DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS website_cache (
                domain      TEXT UNIQUE NOT NULL,
                contacts_json TEXT NOT NULL,
                cached_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_website_cache_domain
                ON website_cache(domain);

            -- F1: Resend webhook email event tracking
            CREATE TABLE IF NOT EXISTS email_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id    INTEGER REFERENCES email_drafts(id),
                resend_id   TEXT,
                event_type  TEXT NOT NULL,
                payload     TEXT,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_email_events_draft
                ON email_events(draft_id);
            CREATE INDEX IF NOT EXISTS idx_email_events_resend
                ON email_events(resend_id);
            CREATE INDEX IF NOT EXISTS idx_email_events_type
                ON email_events(event_type);

            -- F4: LinkedIn outreach messages
            CREATE TABLE IF NOT EXISTS linkedin_messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id     INTEGER NOT NULL REFERENCES prospects(id),
                draft_id        INTEGER REFERENCES email_drafts(id),
                message_type    TEXT NOT NULL DEFAULT 'connection_request',
                message_text    TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL,
                copied_at       TEXT,
                sent_at         TEXT,
                replied_at      TEXT,
                notes           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_linkedin_messages_prospect
                ON linkedin_messages(prospect_id);
            CREATE INDEX IF NOT EXISTS idx_linkedin_messages_draft
                ON linkedin_messages(draft_id);
            CREATE INDEX IF NOT EXISTS idx_linkedin_messages_status
                ON linkedin_messages(status);

            -- F3+F5: additional indexes for sequences and variants
            CREATE INDEX IF NOT EXISTS idx_email_drafts_parent
                ON email_drafts(parent_draft_id);
            CREATE INDEX IF NOT EXISTS idx_email_drafts_resend
                ON email_drafts(resend_id);

            -- C2: CRM Pipeline stages
            CREATE TABLE IF NOT EXISTS prospect_stages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prospect_id     INTEGER NOT NULL REFERENCES prospects(id),
                stage           TEXT NOT NULL DEFAULT 'New',
                moved_at        TEXT NOT NULL,
                notes           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_prospect_stages_prospect
                ON prospect_stages(prospect_id);
            CREATE INDEX IF NOT EXISTS idx_prospect_stages_stage
                ON prospect_stages(stage);

            -- Suppression list: never send to these addresses again
            CREATE TABLE IF NOT EXISTS suppressions (
                email       TEXT UNIQUE NOT NULL,
                reason      TEXT NOT NULL DEFAULT 'bounce',
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_suppressions_email
                ON suppressions(email);

            -- Lead scores v2 (per-domain, with component breakdown)
            CREATE TABLE IF NOT EXISTS lead_scores (
                domain          TEXT UNIQUE NOT NULL,
                score           INTEGER NOT NULL DEFAULT 0,
                level           TEXT NOT NULL DEFAULT 'cold',
                components_json TEXT NOT NULL DEFAULT '{}',
                computed_at     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lead_scores_score
                ON lead_scores(score);

            -- Audit log: who did what, when (dashboard + scheduler actions)
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                actor       TEXT NOT NULL DEFAULT 'dashboard',
                action      TEXT NOT NULL,
                entity      TEXT NOT NULL DEFAULT '',
                entity_id   TEXT NOT NULL DEFAULT '',
                detail      TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_log_created
                ON audit_log(created_at);

            -- Inbox processor: already-handled reply Message-IDs
            CREATE TABLE IF NOT EXISTS inbox_processed (
                message_id  TEXT UNIQUE NOT NULL,
                processed_at TEXT NOT NULL
            );
        """


def _split_schema() -> tuple[list[str], list[str]]:
    """Split _SCHEMA into (create_tables, create_indexes) statement lists."""
    tables: list[str] = []
    indexes: list[str] = []
    for chunk in _SCHEMA.split(";"):
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue
        upper = stmt.upper()
        if upper.startswith("CREATE TABLE"):
            tables.append(stmt)
        elif upper.startswith("CREATE INDEX"):
            indexes.append(stmt)
        else:
            raise ValueError(f"Unexpected statement in _SCHEMA: {stmt[:60]!r}")
    return tables, indexes


def init_db() -> None:
    """Create base tables, apply migrations, then create indexes."""
    tables, indexes = _split_schema()
    with get_connection() as conn:
        for stmt in tables:
            conn.execute(stmt)
        _migrate(conn)
        for stmt in indexes:
            conn.execute(stmt)
    logger.info("Database initialised at %s", DB_PATH)


# ------------------------------------------------------------------
# Job postings
# ------------------------------------------------------------------


def insert_job_posting(data: dict) -> int | None:
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
             location, url, keyword_matched, published_at, scraped_at, status)
        VALUES
            (:source, :external_id, :title, :company_name, :company_domain, :org_number,
             :location, :url, :keyword_matched, :published_at, :scraped_at, :status)
    """
    data.setdefault("source", "finn")
    data.setdefault("status", "active")
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


def update_job_posting(posting_id: int, data: dict) -> None:
    """Update fields on a job posting. Keys must be in the allowlist."""
    unknown = set(data) - _UPDATABLE_COLUMNS["job_postings"]
    if unknown:
        raise ValueError(f"Cannot update job_postings columns: {sorted(unknown)}")
    if not data:
        return
    sets = [f"{key} = ?" for key in data]
    params = list(data.values()) + [posting_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE job_postings SET {', '.join(sets)} WHERE id = ?", params)


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
        conditions.append(
            "(title LIKE ? ESCAPE '\\' OR company_name LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')"
        )
        params.extend([_like_contains(search)] * 3)
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


def get_existing_external_ids(source: str) -> set:
    """Return set of external_id values already in DB for a given source."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT external_id FROM job_postings WHERE source = ?", (source,)
        ).fetchall()
    return {row[0] for row in rows if row[0]}


# ------------------------------------------------------------------
# Prospects
# ------------------------------------------------------------------


def insert_prospect(data: dict) -> int | None:
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


def get_prospect_by_email(email: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM prospects WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None


def get_prospect_by_id(prospect_id: int) -> dict | None:
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
            "(full_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR company_name LIKE ? ESCAPE '\\' OR position LIKE ? ESCAPE '\\')"
        )
        params.extend([_like_contains(search)] * 4)
    if email_status:
        conditions.append("email_status = ?")
        params.append(email_status)
    if company:
        conditions.append("company_name LIKE ? ESCAPE '\\'")
        params.append(_like_contains(company))

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
                {where.replace("full_name", "p.full_name").replace("email LIKE", "p.email LIKE").replace("company_name", "p.company_name").replace("email_status", "p.email_status").replace("position", "p.position")}
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
                ) as outreach_status,
                ls.score as lead_score,
                ls.level as lead_level
            FROM prospects p
            LEFT JOIN job_postings jp ON p.job_posting_id = jp.id
            LEFT JOIN lead_scores ls ON LOWER(ls.domain) = LOWER(p.company_domain)
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


def insert_email_draft(data: dict) -> int | None:
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


def get_draft_status_counts() -> dict:
    """Return {status: count} for all email drafts in a single query."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT COALESCE(status, 'draft') as status, COUNT(*) as cnt FROM email_drafts GROUP BY status"
        ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}


def get_email_draft_by_id(draft_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT ed.*,
                      p.full_name as prospect_name, p.email as prospect_email,
                      p.first_name, p.last_name,
                      p.position as prospect_title,
                      p.company_name, p.company_domain,
                      jp.title as job_title, jp.location as job_location, jp.url as job_url,
                      jp.status as job_posting_status
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               LEFT JOIN job_postings jp ON ed.job_posting_id = jp.id
               WHERE ed.id = ?""",
            (draft_id,),
        ).fetchone()
        return dict(row) if row else None


def update_email_draft(draft_id: int, data: dict) -> None:
    """Update fields on an email draft. Keys must be in the allowlist."""
    unknown = set(data) - _UPDATABLE_COLUMNS["email_drafts"]
    if unknown:
        raise ValueError(f"Cannot update email_drafts columns: {sorted(unknown)}")
    sets = []
    params = []
    for key, val in data.items():
        sets.append(f"{key} = ?")
        params.append(val)
    params.append(draft_id)

    with get_connection() as conn:
        conn.execute(f"UPDATE email_drafts SET {', '.join(sets)} WHERE id = ?", params)


def draft_exists_for_prospect(prospect_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM email_drafts WHERE prospect_id = ?", (prospect_id,)
        ).fetchone()
        return row is not None


def get_approved_drafts_with_prospects() -> list[dict]:
    """Return all approved drafts with prospect data needed for Snov enrollment."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT ed.id, ed.prospect_id, ed.job_posting_id, ed.subject, ed.body, ed.scheduled_for,
                   p.email as prospect_email,
                   p.first_name, p.last_name,
                   p.full_name as prospect_name,
                   p.position as prospect_title,
                   p.company_name, p.company_domain
            FROM email_drafts ed
            JOIN prospects p ON ed.prospect_id = p.id
            WHERE ed.status = 'approved'
            ORDER BY ed.approved_at ASC
        """).fetchall()
    return [dict(r) for r in rows]


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
    """Update fields on a pipeline run. Keys must be in the allowlist."""
    unknown = set(data) - _UPDATABLE_COLUMNS["pipeline_runs"]
    if unknown:
        raise ValueError(f"Cannot update pipeline_runs columns: {sorted(unknown)}")
    sets = []
    params = []
    for key, val in data.items():
        sets.append(f"{key} = ?")
        params.append(val)
    params.append(run_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = ?", params)


def get_recent_pipeline_runs(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_stale_runs(except_id: int | None = None, older_than_hours: int = 12) -> int:
    """Mark 'running' runs older than the cutoff as 'stale'.

    A run that never finished means its process died. Returns rows marked.
    started_at is stored as naive UTC ISO (with 'T'); normalize for SQLite.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE pipeline_runs
               SET status = 'stale', finished_at = ?
               WHERE status = 'running'
                 AND (? IS NULL OR id != ?)
                 AND replace(started_at, 'T', ' ') < datetime('now', ?)""",
            (
                _now(),
                except_id,
                except_id,
                f"-{int(older_than_hours)} hours",
            ),
        )
        return cur.rowcount


def get_pipeline_run_trends(days: int = 30) -> list[dict]:
    """Return daily aggregated pipeline stats over last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                DATE(started_at) as day,
                SUM(postings_scraped) as total_scraped,
                SUM(COALESCE(prospects_found, 0)) as total_prospects,
                COUNT(*) as run_count
            FROM pipeline_runs
            WHERE started_at >= DATE('now', ?)
              AND status = 'completed'
            GROUP BY DATE(started_at)
            ORDER BY day""",
            (f"-{days} days",),
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

        today = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d")
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


def get_job_posting_by_id(posting_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM job_postings WHERE id = ?", (posting_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_job_postings(posting_ids: list[int]) -> int:
    """Delete job postings and their linked prospects, drafts, outreach logs.

    Returns the number of postings deleted.
    """
    if not posting_ids:
        return 0
    placeholders = ",".join("?" for _ in posting_ids)
    with get_connection() as conn:
        # Get prospect IDs linked to these postings (for cascade)
        prospect_rows = conn.execute(
            f"SELECT id FROM prospects WHERE job_posting_id IN ({placeholders})",
            posting_ids,
        ).fetchall()
        prospect_ids = [r["id"] for r in prospect_rows]

        if prospect_ids:
            p_placeholders = ",".join("?" for _ in prospect_ids)
            # Delete outreach logs for those prospects
            conn.execute(
                f"DELETE FROM outreach_log WHERE prospect_id IN ({p_placeholders})",
                prospect_ids,
            )
            # Delete email drafts for those prospects
            conn.execute(
                f"DELETE FROM email_drafts WHERE prospect_id IN ({p_placeholders})",
                prospect_ids,
            )
            # Delete the prospects themselves
            conn.execute(
                f"DELETE FROM prospects WHERE id IN ({p_placeholders})",
                prospect_ids,
            )

        # Also delete any email drafts linked directly to posting
        conn.execute(
            f"DELETE FROM email_drafts WHERE job_posting_id IN ({placeholders})",
            posting_ids,
        )

        # Delete the postings
        cur = conn.execute(
            f"DELETE FROM job_postings WHERE id IN ({placeholders})",
            posting_ids,
        )
        deleted = cur.rowcount
        logger.info(
            "Deleted %d postings, %d prospects cascaded", deleted, len(prospect_ids)
        )
        return deleted


# ------------------------------------------------------------------
# Companies (BRREG data)
# ------------------------------------------------------------------


def insert_company(data: dict) -> int | None:
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
            logger.debug(
                "Inserted company org=%s name=%s", data["org_number"], data["name"]
            )
            return cur.lastrowid
    return None


def get_company_by_org_number(org_number: str) -> dict | None:
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


def insert_company_role(data: dict) -> int | None:
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
# Website cache
# ------------------------------------------------------------------


def get_cached_contacts(domain: str, ttl_days: int = 7) -> list | None:
    """Return cached contacts for domain, or None if expired/missing."""
    import json

    with get_connection() as conn:
        row = conn.execute(
            "SELECT contacts_json, cached_at FROM website_cache WHERE domain = ?",
            (domain,),
        ).fetchone()
    if not row:
        return None
    cached_at = datetime.fromisoformat(row["cached_at"])
    age_days = (datetime.now(UTC).replace(tzinfo=None) - cached_at).days
    if age_days > ttl_days:
        return None
    return json.loads(row["contacts_json"])


def cache_contacts(domain: str, contacts: list) -> None:
    """Store or update cached contacts for a domain."""
    import json

    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO website_cache (domain, contacts_json, cached_at) VALUES (?, ?, ?)",
            (domain, json.dumps(contacts), _now()),
        )


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
            rows = conn.execute("SELECT * FROM keywords ORDER BY keyword").fetchall()
    return [dict(r) for r in rows]


def get_keyword_list() -> list[str]:
    """Return a plain list of active keyword strings."""
    return [kw["keyword"] for kw in get_keywords(active_only=True)]


def add_keyword(keyword: str) -> int | None:
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
# Email Events (F1 — Resend webhook tracking)
# ------------------------------------------------------------------


def insert_email_event(data: dict) -> int | None:
    """Insert a Resend webhook event. Returns event id."""
    sql = """
        INSERT INTO email_events (draft_id, resend_id, event_type, payload, created_at)
        VALUES (:draft_id, :resend_id, :event_type, :payload, :created_at)
    """
    data.setdefault("created_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        return cur.lastrowid if cur.lastrowid else None


def get_email_events_by_draft(draft_id: int) -> list[dict]:
    """Get all email events for a specific draft, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM email_events WHERE draft_id = ? ORDER BY created_at DESC",
            (draft_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_email_events_by_resend_id(resend_id: str) -> list[dict]:
    """Get all events for a specific Resend email ID."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM email_events WHERE resend_id = ? ORDER BY created_at DESC",
            (resend_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_draft_id_by_resend_id(resend_id: str) -> int | None:
    """Look up draft_id from a Resend email ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM email_drafts WHERE resend_id = ?", (resend_id,)
        ).fetchone()
        return row["id"] if row else None


def get_outreach_stats() -> dict:
    """Get aggregate outreach engagement stats."""
    with get_connection() as conn:
        total_sent = conn.execute(
            "SELECT COUNT(*) FROM email_drafts WHERE status = 'sent'"
        ).fetchone()[0]
        total_opened = conn.execute(
            "SELECT COUNT(DISTINCT draft_id) FROM email_events WHERE event_type = 'opened'"
        ).fetchone()[0]
        total_clicked = conn.execute(
            "SELECT COUNT(DISTINCT draft_id) FROM email_events WHERE event_type = 'clicked'"
        ).fetchone()[0]
        total_bounced = conn.execute(
            "SELECT COUNT(DISTINCT draft_id) FROM email_events WHERE event_type = 'bounced'"
        ).fetchone()[0]
        total_delivered = conn.execute(
            "SELECT COUNT(DISTINCT draft_id) FROM email_events WHERE event_type = 'delivered'"
        ).fetchone()[0]

    open_rate = (total_opened / total_sent * 100) if total_sent > 0 else 0.0
    click_rate = (total_clicked / total_sent * 100) if total_sent > 0 else 0.0
    bounce_rate = (total_bounced / total_sent * 100) if total_sent > 0 else 0.0

    return {
        "total_sent": total_sent,
        "total_delivered": total_delivered,
        "total_opened": total_opened,
        "total_clicked": total_clicked,
        "total_bounced": total_bounced,
        "open_rate": round(open_rate, 1),
        "click_rate": round(click_rate, 1),
        "bounce_rate": round(bounce_rate, 1),
    }


def get_engagement_timeline(days: int = 30) -> list[dict]:
    """Daily email engagement data (sends, opens, clicks) over last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT
                DATE(created_at) as day,
                SUM(CASE WHEN event_type = 'delivered' THEN 1 ELSE 0 END) as delivered,
                SUM(CASE WHEN event_type = 'opened' THEN 1 ELSE 0 END) as opened,
                SUM(CASE WHEN event_type = 'clicked' THEN 1 ELSE 0 END) as clicked
            FROM email_events
            WHERE created_at >= DATE('now', ?)
            GROUP BY DATE(created_at)
            ORDER BY day""",
            (f"-{days} days",),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Follow-up Sequences (F3)
# ------------------------------------------------------------------


def get_sent_drafts_needing_followup(
    min_days: int = 3, max_step: int = 3
) -> list[dict]:
    """Get drafts sent via Resend that had no open event and need a follow-up.

    Returns drafts where:
    - status = 'sent'
    - resend_id IS NOT NULL (sent via Resend)
    - sent_at >= min_days ago
    - sequence_step < max_step
    - no 'opened' event exists for this draft
    - no reply recorded (event or replied_at) — never chase a responder
    - no bounce recorded for this draft
    - recipient not suppressed
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ed.*, p.full_name as prospect_name, p.email as prospect_email,
                      p.company_name, p.position as prospect_title,
                      jp.title as job_title, jp.keyword_matched
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               LEFT JOIN job_postings jp ON ed.job_posting_id = jp.id
               WHERE ed.status = 'sent'
                 AND ed.resend_id IS NOT NULL
                 AND ed.sent_at <= datetime('now', ?)
                 AND COALESCE(ed.sequence_step, 1) < ?
                 AND NOT EXISTS (
                     SELECT 1 FROM email_events ee
                     WHERE ee.draft_id = ed.id AND ee.event_type = 'opened'
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM email_events ee
                     WHERE ee.draft_id = ed.id
                       AND ee.event_type IN ('replied', 'bounced')
                 )
                 AND ed.replied_at IS NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM suppressions s
                     WHERE LOWER(s.email) = LOWER(p.email)
                 )
               ORDER BY ed.sent_at ASC""",
            (f"-{min_days} days", max_step),
        ).fetchall()
    return [dict(r) for r in rows]


def get_draft_sequence(prospect_id: int) -> list[dict]:
    """Get all drafts for a prospect ordered by sequence step."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ed.*, p.email as prospect_email
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               WHERE ed.prospect_id = ?
               ORDER BY COALESCE(ed.sequence_step, 1) ASC, ed.created_at ASC""",
            (prospect_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# LinkedIn Messages (F4)
# ------------------------------------------------------------------


def insert_linkedin_message(data: dict) -> int | None:
    """Insert a LinkedIn message. Returns message id."""
    sql = """
        INSERT INTO linkedin_messages
            (prospect_id, draft_id, message_type, message_text, status, created_at)
        VALUES
            (:prospect_id, :draft_id, :message_type, :message_text, :status, :created_at)
    """
    data.setdefault("status", "pending")
    data.setdefault("created_at", _now())
    with get_connection() as conn:
        cur = conn.execute(sql, data)
        return cur.lastrowid if cur.lastrowid else None


def get_linkedin_messages_by_prospect(prospect_id: int) -> list[dict]:
    """Get all LinkedIn messages for a prospect."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM linkedin_messages WHERE prospect_id = ? ORDER BY created_at ASC",
            (prospect_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_linkedin_message_by_draft(draft_id: int) -> dict | None:
    """Get LinkedIn message associated with a draft."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM linkedin_messages WHERE draft_id = ? ORDER BY created_at DESC LIMIT 1",
            (draft_id,),
        ).fetchone()
        return dict(row) if row else None


def update_linkedin_message(message_id: int, data: dict) -> None:
    """Update fields on a LinkedIn message. Keys must be in the allowlist."""
    unknown = set(data) - _UPDATABLE_COLUMNS["linkedin_messages"]
    if unknown:
        raise ValueError(f"Cannot update linkedin_messages columns: {sorted(unknown)}")
    sets = []
    params = []
    for key, val in data.items():
        sets.append(f"{key} = ?")
        params.append(val)
    params.append(message_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE linkedin_messages SET {', '.join(sets)} WHERE id = ?", params
        )


# ------------------------------------------------------------------
# Suppression list (never send to these addresses)
# ------------------------------------------------------------------


def add_suppression(email: str, reason: str = "bounce") -> None:
    """Add an address to the suppression list (idempotent)."""
    email = (email or "").strip().lower()
    if not email:
        return
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO suppressions (email, reason, created_at) "
            "VALUES (?, ?, ?)",
            (email, reason, _now()),
        )


def is_suppressed(email: str) -> bool:
    """Return True if the address must never be contacted again."""
    if not email:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM suppressions WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
        return row is not None


def get_suppressions() -> list[dict]:
    """Return the full suppression list (for settings/audit display)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT email, reason, created_at FROM suppressions ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Lead scores v2
# ------------------------------------------------------------------


def upsert_lead_score(
    domain: str, score: int, level: str, components_json: str
) -> None:
    """Insert or replace the v2 score for a company domain."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO lead_scores (domain, score, level, components_json, computed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(domain) DO UPDATE SET
                 score = excluded.score, level = excluded.level,
                 components_json = excluded.components_json,
                 computed_at = excluded.computed_at""",
            (domain, score, level, components_json, _now()),
        )


def get_lead_scores(limit: int = 100, min_score: int = 0) -> list[dict]:
    """Top-scoring domains with their component breakdowns."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT domain, score, level, components_json, computed_at
               FROM lead_scores WHERE score >= ?
               ORDER BY score DESC LIMIT ?""",
            (min_score, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_lead_score(domain: str) -> dict | None:
    """Single-domain v2 score with components, or None if never scored."""
    if not domain:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """SELECT domain, score, level, components_json, computed_at
               FROM lead_scores WHERE domain = ?""",
            (domain,),
        ).fetchone()
    return dict(row) if row else None


def get_hot_prospects_v2(limit: int = 10) -> list[dict]:
    """Prospects at the highest-scored companies (v2), hottest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.*, ls.score, ls.level, ls.components_json,
                      jp.title as job_title, jp.company_domain
               FROM prospects p
               JOIN lead_scores ls ON LOWER(ls.domain) = LOWER(p.company_domain)
               LEFT JOIN job_postings jp ON p.job_posting_id = jp.id
               ORDER BY ls.score DESC, p.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Audit log
# ------------------------------------------------------------------


def log_audit(
    actor: str,
    action: str,
    entity: str = "",
    entity_id: str | int = "",
    detail: str = "",
) -> None:
    """Record who performed a mutating action. Never raises."""
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO audit_log (actor, action, entity, entity_id, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (actor or "dashboard", action, entity, str(entity_id), detail, _now()),
            )
    except Exception as exc:
        logger.warning("Audit log write failed (%s %s): %s", action, entity_id, exc)


def get_audit_log(limit: int = 100) -> list[dict]:
    """Most recent audit entries, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT actor, action, entity, entity_id, detail, created_at
               FROM audit_log ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Inbox processor (reply idempotency)
# ------------------------------------------------------------------


def inbox_already_processed(message_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM inbox_processed WHERE message_id = ?", (message_id,)
        ).fetchone()
        return row is not None


def mark_inbox_processed(message_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO inbox_processed (message_id, processed_at)"
            " VALUES (?, ?)",
            (message_id, _now()),
        )


def get_domains_for_career_scan(limit: int = 30, since_days: int = 90) -> list[dict]:
    """Company domains seen recently, for bounded career-page revisits."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT company_domain AS domain, MAX(company_name) AS company_name,
                      MAX(scraped_at) AS last_seen
               FROM job_postings
               WHERE company_domain IS NOT NULL AND company_domain != ''
                 AND scraped_at >= date('now', ?)
               GROUP BY company_domain
               ORDER BY last_seen DESC
               LIMIT ?""",
            (f"-{since_days} days", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_company_website(
    org_number: str | None = None, company_name: str | None = None
) -> str | None:
    """Company website domain from the local BRREG table (free, no credits).

    Tries exact org match, then fuzzy name match. Returns a clean domain
    (no scheme, no www, lowercase) or None.
    """
    from urllib.parse import urlparse

    def _clean(raw: str | None) -> str | None:
        if not raw:
            return None
        raw = raw.strip()
        if not raw:
            return None
        netloc = urlparse(raw if "://" in raw else f"https://{raw}").netloc.lower()
        netloc = netloc.removeprefix("www.")
        return netloc or None

    with get_connection() as conn:
        if org_number:
            row = conn.execute(
                "SELECT website FROM companies WHERE org_number = ?", (org_number,)
            ).fetchone()
            if row:
                cleaned = _clean(row[0])
                if cleaned:
                    return cleaned
        if company_name:
            from rapidfuzz import fuzz, process

            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM companies WHERE name IS NOT NULL"
                ).fetchall()
            ]
            match = process.extractOne(
                company_name, names, scorer=fuzz.token_sort_ratio, score_cutoff=85
            )
            if match:
                row = conn.execute(
                    "SELECT website FROM companies WHERE name = ?", (match[0],)
                ).fetchone()
                if row:
                    return _clean(row[0])
    return None


def get_postings_for_revalidation(
    limit: int = 50, older_than_days: int = 7
) -> list[dict]:
    """Postings whose liveness is stale: never checked, or not checked
    recently. Expired ones are excluded (already decided). Oldest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, url, source, status FROM job_postings
               WHERE (status IS NULL OR status != 'expired')
                 AND (last_checked_at IS NULL
                      OR replace(last_checked_at, 'T', ' ') < datetime('now', ?))
               ORDER BY last_checked_at ASC NULLS FIRST, scraped_at ASC
               LIMIT ?""",
            (f"-{older_than_days} days", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def posting_is_expired(job_posting_id: int | None) -> bool:
    """True only for positively-expired postings. Unknown/None never blocks."""
    if not job_posting_id:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM job_postings WHERE id = ?", (job_posting_id,)
        ).fetchone()
    return bool(row) and row[0] == "expired"


def get_linkedin_stats() -> dict:
    """Aggregate LinkedIn outreach stats."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM linkedin_messages").fetchone()[0]
        copied = conn.execute(
            "SELECT COUNT(*) FROM linkedin_messages WHERE status IN ('copied','sent','replied')"
        ).fetchone()[0]
        sent = conn.execute(
            "SELECT COUNT(*) FROM linkedin_messages WHERE status IN ('sent','replied')"
        ).fetchone()[0]
        replied = conn.execute(
            "SELECT COUNT(*) FROM linkedin_messages WHERE status = 'replied'"
        ).fetchone()[0]

    reply_rate = (replied / sent * 100) if sent > 0 else 0.0
    return {
        "total": total,
        "copied": copied,
        "sent": sent,
        "replied": replied,
        "reply_rate": round(reply_rate, 1),
    }


def get_linkedin_messages_list(
    status: str = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    """Paginated LinkedIn messages with prospect data."""
    conditions = []
    params = []
    if status:
        conditions.append("lm.status = ?")
        params.append(status)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM linkedin_messages lm {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT lm.*, p.full_name as prospect_name, p.email as prospect_email,
                       p.company_name, p.linkedin_url, p.position as prospect_title
                FROM linkedin_messages lm
                JOIN prospects p ON lm.prospect_id = p.id
                {where}
                ORDER BY lm.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

    return [dict(r) for r in rows], total


# ------------------------------------------------------------------
# AI Variants (F5)
# ------------------------------------------------------------------


def get_draft_variants(draft_id: int) -> list[dict]:
    """Get all variant drafts for a given draft."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ed.*, p.full_name as prospect_name, p.email as prospect_email
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               WHERE ed.variant_of = ?
               ORDER BY ed.created_at ASC""",
            (draft_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# A/B Testing (C1)
# ------------------------------------------------------------------


def get_ab_test_groups() -> list[dict]:
    """Get all drafts that have variants, grouped with engagement stats."""
    with get_connection() as conn:
        # Find all parent drafts that have at least one variant
        parents = conn.execute(
            """SELECT DISTINCT variant_of FROM email_drafts
               WHERE variant_of IS NOT NULL""",
        ).fetchall()

        results = []
        for row in parents:
            parent_id = row[0]
            parent = conn.execute(
                """SELECT ed.*, p.full_name as prospect_name, p.email as prospect_email,
                          p.company_name
                   FROM email_drafts ed
                   JOIN prospects p ON ed.prospect_id = p.id
                   WHERE ed.id = ?""",
                (parent_id,),
            ).fetchone()
            if not parent:
                continue

            parent = dict(parent)

            # Get all variants including parent
            variants = conn.execute(
                """SELECT ed.*, p.full_name as prospect_name, p.email as prospect_email
                   FROM email_drafts ed
                   JOIN prospects p ON ed.prospect_id = p.id
                   WHERE ed.id = ? OR ed.variant_of = ?
                   ORDER BY ed.id ASC""",
                (parent_id, parent_id),
            ).fetchall()

            parent["variants"] = [dict(v) for v in variants]
            parent["variant_count"] = len(parent["variants"])

            # Winner: replies dominate, then clicks, then opens — and only
            # with enough signal (min sample), otherwise no call yet.
            def _variant_score(v: dict) -> int:
                replies = 1 if v.get("replied_at") else 0
                return (
                    replies * 10
                    + (v.get("click_count") or 0) * 3
                    + (v.get("open_count") or 0)
                )

            total_signal = sum(
                (v.get("open_count") or 0) + (v.get("click_count") or 0)
                for v in parent["variants"]
            )
            parent["signal_total"] = total_signal
            if total_signal >= 3 and len(parent["variants"]) > 1:
                best = max(parent["variants"], key=_variant_score)
                parent["winner_id"] = best["id"] if _variant_score(best) > 0 else None
            else:
                parent["winner_id"] = None

            results.append(parent)

    return results


def get_ab_test_results(parent_draft_id: int) -> dict:
    """Get detailed A/B test results for a specific parent draft."""
    with get_connection() as conn:
        parent = conn.execute(
            """SELECT ed.*, p.full_name as prospect_name, p.email as prospect_email,
                      p.company_name
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               WHERE ed.id = ?""",
            (parent_draft_id,),
        ).fetchone()
        if not parent:
            return {}

        variants = conn.execute(
            """SELECT ed.*, p.full_name as prospect_name, p.email as prospect_email
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               WHERE ed.id = ? OR ed.variant_of = ?
               ORDER BY ed.id ASC""",
            (parent_draft_id, parent_draft_id),
        ).fetchall()

    result = dict(parent)
    result["variants"] = [dict(v) for v in variants]
    return result


# ------------------------------------------------------------------
# CRM Pipeline (C2)
# ------------------------------------------------------------------


def get_prospect_stage(prospect_id: int) -> dict | None:
    """Get current pipeline stage for a prospect."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM prospect_stages
               WHERE prospect_id = ?
               ORDER BY moved_at DESC LIMIT 1""",
            (prospect_id,),
        ).fetchone()
    return dict(row) if row else None


def set_prospect_stage(prospect_id: int, stage: str, notes: str = "") -> int:
    """Set pipeline stage for a prospect. Returns new stage record id."""
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO prospect_stages (prospect_id, stage, moved_at, notes)
               VALUES (?, ?, ?, ?)""",
            (prospect_id, stage, _now(), notes),
        )
        conn.commit()
    return cursor.lastrowid


def get_pipeline_board() -> dict:
    """Get all prospects grouped by their current stage for kanban board."""
    stages = ["New", "Contacted", "Opened", "Replied", "Meeting", "Won", "Lost"]
    with get_connection() as conn:
        # Get latest stage per prospect via subquery
        rows = conn.execute(
            """SELECT ps.prospect_id, ps.stage, ps.moved_at, ps.notes,
                      p.full_name, p.email, p.company_name, p.position,
                      p.linkedin_url
               FROM prospect_stages ps
               JOIN prospects p ON ps.prospect_id = p.id
               WHERE ps.id = (
                   SELECT MAX(id) FROM prospect_stages ps2
                   WHERE ps2.prospect_id = ps.prospect_id
               )
               ORDER BY ps.moved_at DESC""",
        ).fetchall()

    board = {s: [] for s in stages}
    for row in rows:
        d = dict(row)
        stage = d.get("stage", "New")
        if stage in board:
            board[stage].append(d)
        else:
            board["New"].append(d)

    return board


def get_pipeline_counts() -> dict:
    """Get count per stage."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT ps.stage, COUNT(*) as cnt
               FROM prospect_stages ps
               WHERE ps.id = (
                   SELECT MAX(id) FROM prospect_stages ps2
                   WHERE ps2.prospect_id = ps.prospect_id
               )
               GROUP BY ps.stage""",
        ).fetchall()
    return {r["stage"]: r["cnt"] for r in rows}


def auto_move_prospect_stage(prospect_id: int, event_type: str) -> None:
    """Auto-move prospect to new stage based on email event."""
    stage_map = {
        "delivered": "Contacted",
        "opened": "Opened",
        "clicked": "Opened",
        "replied": "Replied",
    }
    new_stage = stage_map.get(event_type)
    if not new_stage:
        return

    current = get_prospect_stage(prospect_id)
    if current:
        # Don't move backwards
        stage_order = [
            "New",
            "Contacted",
            "Opened",
            "Replied",
            "Meeting",
            "Won",
            "Lost",
        ]
        current_idx = (
            stage_order.index(current["stage"])
            if current["stage"] in stage_order
            else 0
        )
        new_idx = stage_order.index(new_stage) if new_stage in stage_order else 0
        if new_idx <= current_idx:
            return

    set_prospect_stage(prospect_id, new_stage, f"Auto: {event_type} event")


# ------------------------------------------------------------------
# Intent Signals (C3)
# ------------------------------------------------------------------


def get_company_intent_signals(domain: str) -> dict:
    """Calculate hiring intent signals for a company domain.

    Matches case-insensitively: posting domains are stored as scraped.
    """
    domain = (domain or "").lower()
    live = "(status IS NULL OR status != 'expired')"
    with get_connection() as conn:
        # Count total job postings
        total = conn.execute(
            f"SELECT COUNT(*) FROM job_postings WHERE LOWER(company_domain) = ? AND {live}",
            (domain,),
        ).fetchone()[0]

        # Recent postings (last 30 days)
        recent = conn.execute(
            f"""SELECT COUNT(*) FROM job_postings
               WHERE LOWER(company_domain) = ? AND scraped_at >= date('now', '-30 days') AND {live}""",
            (domain,),
        ).fetchone()[0]

        # Unique keywords
        keywords = conn.execute(
            f"""SELECT DISTINCT keyword_matched FROM job_postings
               WHERE LOWER(company_domain) = ? AND keyword_matched IS NOT NULL AND {live}""",
            (domain,),
        ).fetchall()

    # Calculate intent score (0-100)
    score = 0
    if total >= 1:
        score += 20
    if total >= 3:
        score += 20
    if total >= 5:
        score += 10
    if recent >= 2:
        score += 25  # Active hiring
    if recent >= 4:
        score += 15  # Very active
    if len(keywords) >= 2:
        score += 10  # Multi-keyword

    level = "cold"
    if score >= 70:
        level = "hot"
    elif score >= 45:
        level = "warm"
    elif score >= 20:
        level = "medium"

    return {
        "score": min(score, 100),
        "level": level,
        "total_postings": total,
        "recent_postings": recent,
        "keyword_count": len(keywords),
    }


def update_company_intent_score(domain: str, score: int, signals_json: str) -> None:
    """Store intent score on the company record."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE companies SET intent_score = ?, intent_signals = ?
               WHERE website = ? OR website = ?""",
            (score, signals_json, domain, f"https://{domain}"),
        )
        conn.commit()


def get_hot_prospects(limit: int = 10) -> list[dict]:
    """Get prospects from companies with highest intent signals."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.*, jp.title as job_title, jp.company_domain,
                      (SELECT COUNT(*) FROM job_postings jp2
                       WHERE jp2.company_domain = jp.company_domain) as posting_count
               FROM prospects p
               LEFT JOIN job_postings jp ON p.job_posting_id = jp.id
               WHERE jp.company_domain IS NOT NULL
               ORDER BY posting_count DESC, p.created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Prospect Profile (C4)
# ------------------------------------------------------------------


def get_prospect_full_profile(prospect_id: int) -> dict | None:
    """Get comprehensive prospect profile with all related data."""
    with get_connection() as conn:
        prospect = conn.execute(
            """SELECT p.*, jp.title as job_title, jp.location as job_location,
                      jp.url as job_url, jp.company_domain, jp.org_number,
                      jp.keyword_matched
               FROM prospects p
               LEFT JOIN job_postings jp ON p.job_posting_id = jp.id
               WHERE p.id = ?""",
            (prospect_id,),
        ).fetchone()
        if not prospect:
            return None

        prospect = dict(prospect)

        # Company info from BRREG
        if prospect.get("org_number"):
            company = conn.execute(
                "SELECT * FROM companies WHERE org_number = ?",
                (prospect["org_number"],),
            ).fetchone()
            prospect["company_info"] = dict(company) if company else None
        else:
            prospect["company_info"] = None

        # Email drafts
        drafts = conn.execute(
            """SELECT id, subject, status, template_name, created_at, sent_at,
                      open_count, click_count
               FROM email_drafts WHERE prospect_id = ?
               ORDER BY created_at DESC""",
            (prospect_id,),
        ).fetchall()
        prospect["drafts"] = [dict(d) for d in drafts]

        # LinkedIn messages
        li_msgs = conn.execute(
            """SELECT * FROM linkedin_messages WHERE prospect_id = ?
               ORDER BY created_at DESC""",
            (prospect_id,),
        ).fetchall()
        prospect["linkedin_messages"] = [dict(m) for m in li_msgs]

        # Email events
        events = conn.execute(
            """SELECT ee.* FROM email_events ee
               JOIN email_drafts ed ON ee.draft_id = ed.id
               WHERE ed.prospect_id = ?
               ORDER BY ee.created_at DESC LIMIT 20""",
            (prospect_id,),
        ).fetchall()
        prospect["email_events"] = [dict(e) for e in events]

        # Pipeline stage
        stage = conn.execute(
            """SELECT * FROM prospect_stages
               WHERE prospect_id = ?
               ORDER BY moved_at DESC LIMIT 1""",
            (prospect_id,),
        ).fetchone()
        prospect["current_stage"] = dict(stage) if stage else None

    return prospect
