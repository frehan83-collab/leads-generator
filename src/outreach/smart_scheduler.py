"""
Smart Send Scheduler (C5) — Calculate optimal send times for email outreach.

Factors:
- Norwegian business hours (08:00-16:00 CET)
- Best days: Tuesday-Thursday
- Peak engagement: 09:00-11:00
- Randomization to avoid spam patterns
"""

import logging
import random
from datetime import UTC, date, datetime, timedelta

logger = logging.getLogger(__name__)

# Norwegian business hours (UTC+1 / UTC+2 DST)
# We target 08:30-11:30 CET as peak engagement window
PEAK_HOURS_START = 8
PEAK_HOURS_END = 11
SECONDARY_START = 13
SECONDARY_END = 15

# Best days for B2B outreach (0=Monday, 4=Friday)
BEST_DAYS = [1, 2, 3]  # Tue, Wed, Thu
OK_DAYS = [0, 4]  # Mon, Fri
AVOID_DAYS = [5, 6]  # Sat, Sun


def calculate_optimal_send_time(
    base_time: datetime = None,
    randomize_minutes: int = 45,
) -> datetime:
    """
    Calculate optimal send time for an email.

    Returns a datetime in UTC when the email should be sent.
    Targets Norwegian business hours with randomization.
    """
    if base_time is None:
        base_time = datetime.now(UTC)

    # CET offset (simplified: +1 for winter, +2 for summer)
    # Norway uses CET (UTC+1) / CEST (UTC+2)
    month = base_time.month
    cet_offset = 2 if 3 <= month <= 10 else 1  # Rough DST approximation

    # Convert to local Norwegian time
    local_hour = base_time.hour + cet_offset
    local_day = base_time.weekday()

    # If already past peak hours today, or it's a weekend, find next good slot
    target_date = base_time.date()

    if local_hour >= PEAK_HOURS_END or local_day in AVOID_DAYS:
        # Move to next business day
        target_date = _next_business_day(base_time)

    # Pick a random time within peak window
    target_hour = random.randint(PEAK_HOURS_START, PEAK_HOURS_END)
    target_minute = random.randint(0, randomize_minutes)

    # Convert back to UTC
    send_time = datetime.combine(
        target_date,
        datetime.min.time().replace(hour=target_hour, minute=target_minute),
    )
    # Subtract CET offset to get UTC
    send_time_utc = send_time - timedelta(hours=cet_offset)
    send_time_utc = send_time_utc.replace(tzinfo=UTC)

    # Ensure it's in the future
    if send_time_utc <= base_time:
        # Move to next business day
        target_date = _next_business_day(base_time + timedelta(days=1))
        send_time = datetime.combine(
            target_date,
            datetime.min.time().replace(hour=target_hour, minute=target_minute),
        )
        send_time_utc = send_time - timedelta(hours=cet_offset)
        send_time_utc = send_time_utc.replace(tzinfo=UTC)

    logger.debug(
        "Scheduled send for %s (Norwegian time: %02d:%02d)",
        send_time_utc.isoformat(),
        target_hour,
        target_minute,
    )

    return send_time_utc


def _next_business_day(from_date: datetime) -> "date":
    """Find the next Tuesday-Thursday, or Monday/Friday as fallback."""
    d = from_date.date() + timedelta(days=1)

    # First try to land on Tue-Thu
    for _ in range(7):
        if d.weekday() in BEST_DAYS:
            return d
        d += timedelta(days=1)

    # Fallback: next Mon-Fri
    d = from_date.date() + timedelta(days=1)
    while d.weekday() in AVOID_DAYS:
        d += timedelta(days=1)
    return d


def get_send_window_description() -> str:
    """Human-readable description of the send window."""
    return f"Tue-Thu {PEAK_HOURS_START:02d}:00-{PEAK_HOURS_END:02d}:00 CET (peak engagement)"


def schedule_draft(draft_id: int) -> str:
    """Calculate and store optimal send time for a draft. Returns ISO timestamp."""
    from src.database import db

    send_time = calculate_optimal_send_time()
    iso = send_time.replace(tzinfo=None).isoformat()
    db.update_email_draft(draft_id, {"scheduled_for": iso})
    logger.info("Draft #%d scheduled for %s", draft_id, iso)
    return iso
