"""
Hard exclusion filters. These run BEFORE any scoring — no injured, suspended,
or clearly-not-playing player should ever reach the scoring stage.

FPL status codes (from bootstrap-static 'elements'):
  a = available, d = doubtful, i = injured, s = suspended, u = unavailable, n = not in squad
"""

AVAILABLE_STATUSES = {"a"}
MIN_CHANCE_OF_PLAYING = 75
ROTATION_RISK_MINUTES_THRESHOLD = 60


def is_hard_excluded(player: dict) -> bool:
    """
    True if this player should never be considered, full stop.
    player is one element dict from bootstrap-static.
    """
    status = player.get("status")
    if status not in AVAILABLE_STATUSES:
        return True

    chance = player.get("chance_of_playing_next_round")
    if chance is not None and chance < MIN_CHANCE_OF_PLAYING:
        return True

    return False


def rotation_risk_flag(player: dict, recent_minutes: list[int]) -> bool:
    """
    True if the player is technically available but barely playing.
    recent_minutes: list of minutes played in the last few gameweeks
    (caller supplies this from element-summary history).
    """
    if not recent_minutes:
        return False
    avg = sum(recent_minutes) / len(recent_minutes)
    return avg < ROTATION_RISK_MINUTES_THRESHOLD


def filter_available_players(elements: list[dict]) -> list[dict]:
    """Returns only players that pass the hard exclusion filter."""
    return [p for p in elements if not is_hard_excluded(p)]
