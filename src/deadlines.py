"""
Deadline detection and message-stage decisions.

Confirmed rule: FPL deadline = 90 minutes before the first fixture of the
gameweek kicks off. We pull deadline_time directly from the FPL API rather
than hardcoding this rule — but we cross-check it against the first
fixture's actual kickoff_time as a sanity check (if they disagree by more
than a few minutes beyond the 90-min rule, something unusual happened and
it's worth flagging rather than silently trusting one source).
"""
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser

EXPECTED_DEADLINE_BUFFER_MINUTES = 90
FINAL_MESSAGE_BUFFER_MINUTES = 150
LATE_CHECK_BUFFER_MINUTES = 15


def parse_iso(ts: str) -> datetime:
    return dateparser.isoparse(ts) if hasattr(dateparser, "isoparse") else dateparser.parse(ts)


def sanity_check_deadline(deadline_time: str, first_kickoff: str) -> dict:
    """
    Returns {"consistent": bool, "diff_minutes": float}. Flags if the stated
    deadline doesn't match (kickoff - 90min) within a small tolerance.
    """
    deadline_dt = parse_iso(deadline_time)
    kickoff_dt = parse_iso(first_kickoff)
    expected_deadline = kickoff_dt - timedelta(minutes=EXPECTED_DEADLINE_BUFFER_MINUTES)
    diff = abs((deadline_dt - expected_deadline).total_seconds()) / 60.0
    return {"consistent": diff <= 5, "diff_minutes": diff}


def current_stage(now: datetime, deadline_time: str, first_kickoff: str) -> str:
    """
    Returns one of: "predicted", "final_window", "late_check_window", "locked".

    - "predicted": more than 1h before deadline (i.e. before the 2h30m-before-
      kickoff mark) -> send/keep the "Predicted Lineup" message
    - "final_window": within the 2h30m-before-kickoff to 15-min-before-deadline
      range -> this is when the "Final Confirmed Lineup" message should fire
      (once, at the start of this window)
    - "late_check_window": within 15 minutes of deadline -> silent check,
      only message if something material changed
    - "locked": deadline has passed
    """
    deadline_dt = parse_iso(deadline_time)
    kickoff_dt = parse_iso(first_kickoff)
    final_message_time = kickoff_dt - timedelta(minutes=FINAL_MESSAGE_BUFFER_MINUTES)
    late_check_time = deadline_dt - timedelta(minutes=LATE_CHECK_BUFFER_MINUTES)

    if now >= deadline_dt:
        return "locked"
    if now >= late_check_time:
        return "late_check_window"
    if now >= final_message_time:
        return "final_window"
    return "predicted"
