"""Reply detection: monitor the sender mailbox for prospect replies.

Why: Resend webhooks see opens/clicks/bounces, never replies. Without
reply detection, follow-up sequences keep emailing people who already
answered (reputation damage) and the CRM never learns what worked.

Pipeline per message: provider fetches candidates → classify
(human / auto-reply / unsubscribe / angry) → record event →
human replies move CRM + stop sequences; unsubscribes suppress.
"""

import logging

logger = logging.getLogger(__name__)
