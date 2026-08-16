"""
Chip tracking + "should we use it now or wait" evaluation.

Official rules (https://fantasy.premierleague.com/en/help/rules), verified
against FPL's own site for 2026/27:
  - 8 chips total: Wildcard, Free Hit, Bench Boost, Triple Captain — one of
    each in the first half of the season, one of each in the second half.
  - First-half set must be played before the Gameweek 19 deadline
    (13:30 GMT, Saturday 2 January 2027). Unused first-half chips are LOST,
    not carried over — they do not roll into the second half.
  - Only ONE chip can be active in any single Gameweek.
  - Wildcard and Free Hit are played when confirming transfers and cannot
    be cancelled once played. Triple Captain and Bench Boost are played on
    the Pick Team page and CAN be cancelled any time before the deadline.
  - Free Hit cannot be played in consecutive Gameweeks (e.g. if played in
    GW19, the next Free Hit can't be played until GW21 at the earliest).
  - Saved free transfers are NOT consumed by playing a Wildcard or Free
    Hit — if you had 2 saved free transfers before playing one of these
    chips, you still have 2 saved free transfers the following Gameweek.
"""

FIRST_HALF_DEADLINE_EVENT = 19  # chip "set 1" must be used before this gameweek's deadline
FIRST_HALF_DEADLINE_ISO = "2027-01-02T13:30:00Z"  # for expiry warnings

CHIP_KEYS_BY_HALF = {
    1: ["wildcard_1", "free_hit_1", "bench_boost_1", "triple_captain_1"],
    2: ["wildcard_2", "free_hit_2", "bench_boost_2", "triple_captain_2"],
}

CANCELLABLE_CHIPS = {"bench_boost_1", "bench_boost_2", "triple_captain_1", "triple_captain_2"}
NON_CANCELLABLE_CHIPS = {"wildcard_1", "wildcard_2", "free_hit_1", "free_hit_2"}


def current_half(current_event: int) -> int:
    return 1 if current_event < FIRST_HALF_DEADLINE_EVENT else 2


def available_chips(chip_state: dict, current_event: int) -> list[str]:
    half = current_half(current_event)
    return [key for key in CHIP_KEYS_BY_HALF[half] if not chip_state.get(key, {}).get("used")]


def expiring_soon(chip_state: dict, current_event: int, warn_within_gameweeks: int = 3) -> list[str]:
    if current_event >= FIRST_HALF_DEADLINE_EVENT:
        return []
    gameweeks_left = FIRST_HALF_DEADLINE_EVENT - current_event
    if gameweeks_left > warn_within_gameweeks:
        return []
    return [key for key in CHIP_KEYS_BY_HALF[1] if not chip_state.get(key, {}).get("used")]


def can_play_free_hit(chip_state: dict, current_event: int) -> tuple[bool, str]:
    for key in ("free_hit_1", "free_hit_2"):
        record = chip_state.get(key, {})
        if record.get("used") and record.get("gameweek") == current_event - 1:
            return False, f"Free Hit was played in GW{record['gameweek']} — cannot play again in consecutive gameweeks."
    return True, ""


def evaluate_bench_boost_opportunity(
    squad_bench_favorability: float,
    upcoming_double_gameweeks: list[int],
    current_event: int,
) -> dict:
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
