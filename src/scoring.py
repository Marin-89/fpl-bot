"""
Player scoring model.

Design note: FPL's own bootstrap-static already includes 'ep_next' (their
official next-gameweek expected-points projection, actively maintained by
FPL itself) plus season-level expected_goals / expected_assists /
expected_goal_involvements and 'form'. We use these as the core signal
rather than reinventing an xG model from scratch — it's free, reliable,
and updated by FPL every gameweek. We layer our own fixture-difficulty and
stability logic on top, which is the part FPL's own numbers don't capture.

Weights are a documented starting point (see spec) — meant to be tuned via
backtesting in review.py, not treated as final.
"""

WEIGHTS = {
    "ep_next": 0.40,
    "form": 0.20,
    "fixture": 0.25,
    "bps_proxy": 0.15,
}


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_within_position(players: list[dict], key: str) -> dict:
    """
    Min-max normalize a numeric field to 0-1, WITHIN a position group only
    (comparing forwards to forwards, not forwards to defenders — scoring
    dynamics differ too much by position to compare raw numbers directly).
    Returns {player_id: normalized_value}.
    """
    values = [_safe_float(p.get(key)) for p in players]
    if not values:
        return {}
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    return {p["id"]: (_safe_float(p.get(key)) - lo) / span for p in players}


def score_players(
    elements: list[dict],
    fixture_favorability: dict,
) -> dict:
    """
    Returns {player_id: predicted_points_score}, comparable within a position
    group (element_type: 1=GK, 2=DEF, 3=MID, 4=FWD).
    """
    scores = {}
    by_position: dict[int, list[dict]] = {}
    for p in elements:
        by_position.setdefault(p["element_type"], []).append(p)

    for position, players in by_position.items():
        ep_norm = normalize_within_position(players, "ep_next")
        form_norm = normalize_within_position(players, "form")
        bps_norm = normalize_within_position(players, "bps")

        for p in players:
            pid = p["id"]
            fixture_score = fixture_favorability.get(pid, 0.5)
            score = (
                WEIGHTS["ep_next"] * ep_norm.get(pid, 0.0)
                + WEIGHTS["form"] * form_norm.get(pid, 0.0)
                + WEIGHTS["fixture"] * fixture_score
                + WEIGHTS["bps_proxy"] * bps_norm.get(pid, 0.0)
            )
            scores[pid] = score

    return scores
