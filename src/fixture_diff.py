"""
Custom fixture difficulty — FPL's own FDR (1-5) is too blunt (see spec
discussion). We build our own from bootstrap-static 'teams' data, which
includes home/away attack & defence strength ratings that FPL itself
maintains and updates through the season.
"""


def team_strength_map(bootstrap: dict) -> dict:
    """team_id -> dict of strength ratings, from bootstrap-static['teams']."""
    return {t["id"]: t for t in bootstrap["teams"]}


def fixture_difficulty_for_player(
    player_team_id: int,
    opponent_team_id: int,
    is_home: bool,
    strengths: dict,
    attacking: bool,
) -> float:
    """
    Returns a 0-1 "favorability" score for this fixture from the player's
    team's perspective (higher = easier / more favorable).

    attacking=True -> we care about the OPPONENT's defensive strength
      (easier to score against a weak defence).
    attacking=False (e.g. clean-sheet-relevant for DEF/GK) -> we care about
      the opponent's attacking strength (easier clean sheet vs weak attack).
    """
    opp = strengths[opponent_team_id]
    if attacking:
        opp_relevant = opp["strength_defence_away"] if is_home else opp["strength_defence_home"]
    else:
        opp_relevant = opp["strength_attack_away"] if is_home else opp["strength_attack_home"]

    normalized = (opp_relevant - 1000) / 400
    normalized = max(0.0, min(1.0, normalized))
    return 1.0 - normalized


def upcoming_fixture_run(
    team_id: int,
    fixtures: list[dict],
    strengths: dict,
    attacking: bool,
    n_gameweeks: int = 5,
) -> float:
    """
    Average fixture favorability over the next N gameweeks for a team.
    Used both for player scoring and for "opportunity team" detection
    (fixture-swing analysis).
    """
    team_fixtures = [
        f for f in fixtures
        if not f.get("finished") and (f.get("team_h") == team_id or f.get("team_a") == team_id)
    ]
    team_fixtures = sorted(team_fixtures, key=lambda f: f.get("event") or 9999)[:n_gameweeks]

    if not team_fixtures:
        return 0.5

    scores = []
    for f in team_fixtures:
        is_home = f["team_h"] == team_id
        opponent = f["team_a"] if is_home else f["team_h"]
        scores.append(
            fixture_difficulty_for_player(team_id, opponent, is_home, strengths, attacking)
        )
    return sum(scores) / len(scores)


def opportunity_teams(
    bootstrap: dict, fixtures: list[dict], attacking: bool = True, n_gameweeks: int = 5, top_n: int = 6
) -> list[int]:
    """
    Returns team_ids with the most favorable upcoming fixture run — i.e. the
    "easy fixtures" teams to look for attacking picks from (or defensive picks
    if attacking=False).
    """
    strengths = team_strength_map(bootstrap)
    scored = [
        (t["id"], upcoming_fixture_run(t["id"], fixtures, strengths, attacking, n_gameweeks))
        for t in bootstrap["teams"]
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [team_id for team_id, _ in scored[:top_n]]


def detect_double_blank_gameweeks(fixtures: list[dict], events: list[dict]) -> dict:
    """
    Returns {event_id: {"doubles": [team_ids], "blanks": [team_ids]}} by
    counting how many fixtures each team has per gameweek. A team with 2+
    fixtures in one event has a double; a team with 0 has a blank.
    """
    all_team_ids = set()
    for f in fixtures:
        all_team_ids.add(f["team_h"])
        all_team_ids.add(f["team_a"])

    result = {}
    for event in events:
        event_id = event["id"]
        counts = {tid: 0 for tid in all_team_ids}
        for f in fixtures:
            if f.get("event") == event_id:
                counts[f["team_h"]] += 1
                counts[f["team_a"]] += 1
        doubles = [tid for tid, c in counts.items() if c >= 2]
        blanks = [tid for tid, c in counts.items() if c == 0]
        if doubles or blanks:
            result[event_id] = {"doubles": doubles, "blanks": blanks}
    return result
