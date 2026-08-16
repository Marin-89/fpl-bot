"""
Post-gameweek review: logs predicted vs actual points automatically (free,
deterministic). Deeper strategic review ("was this the right call, what
should we learn") happens in a weekly chat with Claude, using this log as
the input — see README.

Points-lock guard: as of 2026/27, Gameweek points are locked and marked
final at 9am UK time on the day after the final match of the Gameweek (not
one hour after full time, as in previous seasons). Running the review
before that lock means comparing against provisional numbers that could
still shift — so review.py checks this before logging anything.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .deadlines import parse_iso

UK_TZ = ZoneInfo("Europe/London")


def gameweek_points_locked(fixtures_for_event: list[dict]) -> tuple[bool, str]:
    """
    Returns (locked, message). locked=False means it's too early to trust
    the numbers yet — caller should wait and try again later.
    """
    if not fixtures_for_event:
        return False, "No fixtures found for this gameweek yet."

    if not all(f.get("finished") for f in fixtures_for_event):
        return False, "Not all matches in this gameweek have finished yet."

    last_kickoff = max(parse_iso(f["kickoff_time"]) for f in fixtures_for_event)
    lock_time_uk = last_kickoff.astimezone(UK_TZ).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    now_uk = datetime.now(timezone.utc).astimezone(UK_TZ)

    if now_uk < lock_time_uk:
        return False, f"Points lock at 9am UK on {lock_time_uk.date()} — not reached yet, numbers may still be provisional."
    return True, "Points are final."


def log_gameweek_result(
    state: dict,
    gameweek: int,
    predicted_points: float,
    actual_points: float,
    captain_id: int,
    captain_actual_points: int,
    notes: str = "",
) -> dict:
    entry = {
        "gameweek": gameweek,
        "predicted_points": predicted_points,
        "actual_points": actual_points,
        "error": actual_points - predicted_points,
        "captain_id": captain_id,
        "captain_actual_points": captain_actual_points,
        "notes": notes,
    }
    state["gameweek_history"].append(entry)
    return state


def backtest_weight_signal(history: list[dict]) -> dict:
    if not history:
        return {"mean_abs_error": None, "bias": None, "n_gameweeks": 0}

    errors = [h["error"] for h in history]
    mean_abs_error = sum(abs(e) for e in errors) / len(errors)
    bias = sum(errors) / len(errors)
    return {
        "mean_abs_error": round(mean_abs_error, 2),
        "bias": round(bias, 2),
        "n_gameweeks": len(history),
    }
