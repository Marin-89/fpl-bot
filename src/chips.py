"""
Chip tracking + "should we use it now or wait" evaluation.

FPL rule: each of the 4 chips (Wildcard, Free Hit, Bench Boost, Triple
Captain) is available twice a season — once in the first half (before the
GW19 deadline), once in the second half. We track each half's usage
separately (see state.py: wildcard_1 / wildcard_2 etc.)
"""

FIRST_HALF_DEADLINE_EVENT = 19

CHIP_KEYS_BY_HALF = {
    1: ["wildcard_1", "free_hit", "bench_boost", "triple_captain"],
    2: ["wildcard_2", "free_hit", "bench_boost", "triple_captain"],
}


def available_chips(chip_state: dict, current_event: int) -> list[str]:
    """Which chip keys are still unused and eligible for the current half of the season."""
    half = 1 if current_event < FIRST_HALF_DEADLINE_EVENT else 2
    available = []
    for key in CHIP_KEYS_BY_HALF[half]:
        state_key = key if key.startswith("wildcard") else key
        if not chip_state.get(state_key, {}).get("used"):
            available.append(key)
    return available


def evaluate_bench_boost_opportunity(
    squad_bench_favorability: float,
    upcoming_double_gameweeks: list[int],
    current_event: int,
) -> dict:
    """
    Simple now-vs-later heuristic for Bench Boost: is there a known Double
    Gameweek coming up that would be a materially better opportunity than
    right now? Returns a recommendation dict with reasoning, doesn't
    auto-decide.
    """
    future_dgws = [gw for gw in upcoming_double_gameweeks if gw > current_event]
    if future_dgws:
        return {
            "recommend_now": False,
            "reason": (
                f"A Double Gameweek is known at GW{future_dgws[0]} — Bench Boost is "
                f"typically stronger there than on a single gameweek now. Worth waiting "
                f"unless your bench favorability this week is unusually high."
            ),
        }
    if squad_bench_favorability > 0.7:
        return {
            "recommend_now": True,
            "reason": "No known upcoming Double Gameweek, and your bench has strong fixtures now.",
        }
    return {
        "recommend_now": False,
        "reason": "No strong signal either way yet — holding is the lower-risk default.",
    }


def evaluate_wildcard_opportunity(
    squad_score_vs_optimal_gap: float,
    fixture_swing_detected: bool,
) -> dict:
    """
    Rough heuristic: a Wildcard is worth flagging when the gap between your
    current squad's total score and a freshly-optimized squad's score is
    large, especially if it coincides with a fixture swing (several squad
    players' teams entering a run of tough fixtures at once).
    """
    if squad_score_vs_optimal_gap > 0.25 and fixture_swing_detected:
        return {
            "recommend_now": True,
            "reason": (
                "Your current squad is scoring notably below what a rebuilt squad could, "
                "and several of your players' teams are entering a tougher fixture run — "
                "this is a reasonable Wildcard window."
            ),
        }
    return {
        "recommend_now": False,
        "reason": "Current squad remains close to optimal — save the Wildcard for a clearer window.",
    }
