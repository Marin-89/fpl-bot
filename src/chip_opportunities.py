"""
Daily chip-opportunity check. Runs once per day (not every scheduler tick —
see main.py's date-gate), evaluates whether Triple Captain, Bench Boost, or
Wildcard look like a good fit for the CURRENT gameweek, and sends a Telegram
message if so. Deliberately conservative: this flags a plausible opportunity
for you to weigh, not a command — chips are irreversible once played, and
timing is genuinely judgment-heavy (see spec discussion). Cross-check any
flagged opportunity in a weekly chat before committing a chip.
"""
from . import chips as chips_mod, fixture_diff, squad_builder


def compute_bench_favorability(bench_players: list[dict], scores: dict) -> float:
    """Average position-normalized score of the bench — used as a rough
    proxy for 'is my bench actually worth boosting this week'."""
    if not bench_players:
        return 0.0
    return sum(scores.get(p["id"], 0) for p in bench_players) / len(bench_players)


def compute_squad_vs_optimal_gap(
    current_squad_xi_score: float, elements: list[dict], scores: dict, budget: float
) -> float:
    """
    Rough estimate of how far your current squad's starting XI score sits
    below a freshly-optimized squad's XI score, as a fraction (0-1). Used
    as a Wildcard trigger — a big gap suggests your squad has drifted from
    what's actually scoring well.
    """
    try:
        optimal_ids = squad_builder.build_optimal_squad(elements, scores, budget=budget)
    except RuntimeError:
        return 0.0  # optimizer couldn't solve — don't false-trigger a wildcard signal
    by_id = {p["id"]: p for p in elements}
    optimal_players = [by_id[pid] for pid in optimal_ids if pid in by_id]
    # Rough XI proxy: top 11 by score among the optimal squad (formation-agnostic estimate).
    optimal_score = sum(sorted((scores.get(p["id"], 0) for p in optimal_players), reverse=True)[:11])
    if optimal_score <= 0:
        return 0.0
    return max(0.0, (optimal_score - current_squad_xi_score) / optimal_score)


def detect_fixture_swing(squad_team_ids: set[int], fixtures: list[dict], strengths: dict) -> bool:
    """
    True if your squad's teams, on average, face a noticeably tougher
    fixture run over the NEXT 3 gameweeks than the following 3 — i.e. a
    rough patch is arriving. Used as a Wildcard signal alongside the score gap.
    """
    if not squad_team_ids:
        return False
    near_scores, later_scores = [], []
    for team_id in squad_team_ids:
        near = fixture_diff.upcoming_fixture_run(team_id, fixtures, strengths, attacking=True, n_gameweeks=3)
        later_fixtures = [f for f in fixtures if not f.get("finished")]
        later = fixture_diff.upcoming_fixture_run(team_id, later_fixtures, strengths, attacking=True, n_gameweeks=6)
        near_scores.append(near)
        later_scores.append(later)
    avg_near = sum(near_scores) / len(near_scores)
    avg_later = sum(later_scores) / len(later_scores)
    return avg_near < avg_later - 0.1  # near-term run meaningfully worse than the wider window


def evaluate_triple_captain_opportunity(
    candidate_name: str, candidate_ep: float, ep_history: list[float]
) -> dict:
    """
    Compares this week's best captain candidate's raw ep_next against a
    rolling history of past weeks' best-candidate ep_next values. Flags it
    as a strong Triple Captain week if it's meaningfully above that
    baseline — requires at least 3 prior weeks of history to avoid
    over-reacting to early-season noise, where ep_next values are still
    compressed (see spec discussion on pre-season data).
    """
    if len(ep_history) < 3:
        return {
            "recommend_now": False,
            "reason": f"Not enough history yet to judge — {candidate_name} projects {candidate_ep:.1f} pts, "
                      f"but need a few more gameweeks of data before flagging a strong TC week.",
        }
    baseline = sum(ep_history) / len(ep_history)
    if candidate_ep > baseline * 1.3:
        return {
            "recommend_now": True,
            "reason": f"{candidate_name} projects {candidate_ep:.1f} pts, notably above your recent "
                      f"captain baseline of {baseline:.1f} — could be a strong Triple Captain week.",
        }
    return {
        "recommend_now": False,
        "reason": f"{candidate_name} projects {candidate_ep:.1f} pts, in line with recent captain baseline "
                  f"of {baseline:.1f} — not a standout week for Triple Captain.",
    }


def run_daily_chip_check(state: dict, bootstrap: dict, elements: list[dict], all_fixtures: list[dict],
                          scores: dict, ep_scores: dict, current_event: int, squad_players: list[dict],
                          starters: list[dict], bench_players: list[dict], captain_id: int, budget_estimate: float) -> list[str]:
    """
    Returns a list of human-readable opportunity messages (empty if
    nothing stands out this week). Also updates state's captain ep history
    in place — caller is responsible for saving state afterward.
    """
    messages = []
    chip_state = state["chips"]
    available = chips_mod.available_chips(chip_state, current_event)
    strengths = fixture_diff.team_strength_map(bootstrap)

    # --- Triple Captain ---
    tc_keys = [k for k in available if k.startswith("triple_captain")]
    if tc_keys:
        captain = next((p for p in starters if p["id"] == captain_id), None)
        if captain:
            candidate_ep = ep_scores.get(captain_id, 0.0)
            history = state.setdefault("captain_ep_history", [])
            result = evaluate_triple_captain_opportunity(captain["web_name"], candidate_ep, history)
            if result["recommend_now"]:
                messages.append(f"🔺 *Triple Captain* ({tc_keys[0].replace('_', ' ').title()}): {result['reason']}")
            history.append(candidate_ep)
            state["captain_ep_history"] = history[-10:]  # keep a bounded rolling window

    # --- Bench Boost ---
    bb_keys = [k for k in available if k.startswith("bench_boost")]
    if bb_keys:
        events = bootstrap.get("events", [])
        dgw_map = fixture_diff.detect_double_blank_gameweeks(all_fixtures, events)
        squad_team_ids = {p["team"] for p in squad_players}
        upcoming_dgws = [
            gw for gw, info in dgw_map.items()
            if gw > current_event and any(t in squad_team_ids for t in info.get("doubles", []))
        ]
        bench_fav = compute_bench_favorability(bench_players, scores)
        result = chips_mod.evaluate_bench_boost_opportunity(bench_fav, upcoming_dgws, current_event)
        if result["recommend_now"]:
            messages.append(f"🪑 *Bench Boost* ({bb_keys[0].replace('_', ' ').title()}): {result['reason']}")

    # --- Wildcard ---
    wc_keys = [k for k in available if k.startswith("wildcard")]
    if wc_keys:
        current_xi_score = sum(scores.get(p["id"], 0) for p in starters)
        gap = compute_squad_vs_optimal_gap(current_xi_score, elements, scores, budget_estimate)
        squad_team_ids = {p["team"] for p in squad_players}
        swing = detect_fixture_swing(squad_team_ids, all_fixtures, strengths)
        result = chips_mod.evaluate_wildcard_opportunity(gap, swing)
        if result["recommend_now"]:
            messages.append(f"🃏 *Wildcard* ({wc_keys[0].replace('_', ' ').title()}): {result['reason']}")

    return messages
