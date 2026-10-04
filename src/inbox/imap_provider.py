"""Generic IMAP inbox provider (Gmail, Fastmail, any IMAP server).

Read-only: messages are never flagged \\Seen, never moved, never deleted.
Already-processed Message-IDs are tracked in inbox_processed so re-runs
are cheap and idempotent.

NOTE on Microsoft 365 / Outlook: Microsoft retired basic-auth IMAP, so a
plain password will NOT work there — that tenant needs the Graph provider
(roadmap). Any IMAP server with password/app-password auth works here.
"""

import email
import email.policy
import email.utils
import imaplib
import logging
import time

from src.inbox.base import InboxMessage

logger = logging.getLogger(__name__)


class ImapInboxProvider:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 993,
        folder: str = "INBOX",
    ):
        if not all([host, username, password]):
            raise ValueError("IMAP host/username/password are all required")
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.folder = folder

    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            conn = imaplib.IMAP4_SSL(self.host, self.port)
            conn.login(self.username, self.password)
            status, _ = conn.select(self.folder, readonly=True)
            if status != "OK":
                raise ConnectionError(f"Cannot select folder {self.folder!r}")
            return conn
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ConnectionError(
                f"IMAP login failed for {self.username}@{self.host} "
                "(check host, app-password, and that basic-auth IMAP is allowed; "
                "M365 tenants need the Graph provider instead)"
            ) from exc

    def fetch_candidates(
        self, since_days: int = 7, limit: int = 100
    ) -> list[InboxMessage]:
        conn = self._connect()
        try:
            since = time.strftime(
                "%d-%b-%Y", time.localtime(time.time() - since_days * 86400)
            )
            status, data = conn.search(None, f"(SINCE {since})")
            if status != "OK":
                return []
            ids = data[0].split()[-limit:]
            out: list[InboxMessage] = []
            for num in ids:
                try:
                    msg = self._fetch_one(conn, num)
                    if msg:
                        out.append(msg)
                except Exception as exc:
                    logger.debug("Skipping message %s: %s", num, exc)
            # newest first so threading prefers the latest touch
            return sorted(out, key=lambda m: m.date or "", reverse=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass
            try:
                conn.logout()
            except Exception:
                pass

    def _fetch_one(self, conn: imaplib.IMAP4_SSL, num: bytes) -> InboxMessage | None:
        status, data = conn.fetch(num, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return None
        raw = data[0][1] if isinstance(data[0], tuple) else data[0]
        parsed = email.message_from_bytes(raw, policy=email.policy.default)
        from_name, from_email = email.utils.parseaddr(parsed.get("From", ""))
        if not from_email:
            return None
        body = self._body_text(parsed)
        return InboxMessage(
            message_id=(parsed.get("Message-ID", "") or "").strip() or f"imap-{num!r}",
            from_email=from_email.strip().lower(),
            from_name=from_name or "",
            subject=(parsed.get("Subject", "") or "").strip(),
            snippet=body[:2000],
            date=(parsed.get("Date", "") or "").strip(),
            in_reply_to=(parsed.get("In-Reply-To", "") or "").strip(),
            references=(parsed.get("References", "") or "").strip(),
            headers={
                "Auto-Submitted": parsed.get("Auto-Submitted", ""),
                "X-Auto-Response-Suppress": parsed.get("X-Auto-Response-Suppress", ""),
            },
        )

    @staticmethod
    def _body_text(parsed) -> str:
        try:
            if parsed.is_multipart():
                for part in parsed.walk():
                    if (
                        part.get_content_type() == "text/plain"
                        and not part.get_filename()
                    ):
                        return str(part.get_content())
                for part in parsed.walk():
                    if (
                        part.get_content_type() == "text/html"
                        and not part.get_filename()
                    ):
                        return str(part.get_content())
                return ""
            return str(parsed.get_content())
        except Exception:
            return ""
