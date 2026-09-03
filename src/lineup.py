"""
Given a fixed 15-man squad, picks the best starting XI + bench order for
THIS gameweek, applies the stability rule against the previously sent
lineup, and labels every player with an exact tactical position.

Manual locks: the user can force a player to start (locked_start) or force
them to the bench (locked_bench) via state["squad"]. These are respected on
every run — the algorithm fills the remaining slots around them, the same
way captain/vice overrides already work. Locks persist until the user
clears them; if a locked player is ever sold or otherwise leaves the
squad, the lock has no effect (nothing to enforce).
"""

LEGAL_FORMATIONS = [
    (3, 4, 3), (3, 5, 2), (4, 4, 2), (4, 3, 3),
    (4, 5, 1), (5, 4, 1), (5, 3, 2), (5, 2, 3),
]

FORMATION_PREFERENCE = {
    (3, 5, 2): 1.05,
    (3, 4, 3): 1.05,
    (4, 4, 2): 1.02,
    (4, 3, 3): 1.02,
    (4, 5, 1): 1.00,
    (5, 2, 3): 0.98,
    (5, 3, 2): 0.95,
    (5, 4, 1): 0.94,
}

POSITION_LABELS = {
    "DEF": {
        3: ["LCB", "CB", "RCB"],
        4: ["LB", "LCB", "RCB", "RB"],
        5: ["LWB", "LCB", "CB", "RCB", "RWB"],
    },
    "MID": {
        2: ["LCM", "RCM"],
        3: ["LM", "CM", "RM"],
        4: ["LM", "LCM", "RCM", "RM"],
        5: ["LM", "LCM", "CM", "RCM", "RM"],
    },
    "FWD": {
        1: ["ST"],
        2: ["LST", "RST"],
        3: ["LST", "CST", "RST"],
    },
}

STABILITY_THRESHOLD = 0.08
TRANSFER_CONVICTION_THRESHOLD = 0.15

CAPTAINCY_CEILING_MULTIPLIER = {
    4: 1.15,
    3: 1.08,
    2: 1.00,
}


def label_positions(starters: list[dict], formation: tuple[int, int, int]) -> list[dict]:
    def_count, mid_count, fwd_count = formation
    gk = [p for p in starters if p["element_type"] == 1]
    defs = [p for p in starters if p["element_type"] == 2]
    mids = [p for p in starters if p["element_type"] == 3]
    fwds = [p for p in starters if p["element_type"] == 4]

    labeled = []
    for p in gk:
        labeled.append({**p, "tactical_position": "GK"})
    for p, label in zip(defs, POSITION_LABELS["DEF"][def_count]):
        labeled.append({**p, "tactical_position": label})
    for p, label in zip(mids, POSITION_LABELS["MID"][mid_count]):
        labeled.append({**p, "tactical_position": label})
    for p, label in zip(fwds, POSITION_LABELS["FWD"][fwd_count]):
        labeled.append({**p, "tactical_position": label})
    return labeled


def _position_pool(squad: list[dict], scores: dict, etype: int, locked_start: set, locked_bench: set) -> list[dict]:
    """
    Players of this position, with locked-to-start players placed first
    (guaranteeing inclusion when the caller slices the top N), locked-to-bench
    players excluded entirely, and everyone else sorted by score.
    """
    players = [p for p in squad if p["element_type"] == etype and p["id"] not in locked_bench]
    forced = [p for p in players if p["id"] in locked_start]
    rest = [p for p in players if p["id"] not in locked_start]
    rest.sort(key=lambda p: -scores.get(p["id"], 0))
    return forced + rest


def best_formation_and_xi(
    squad: list[dict],
    scores: dict,
    locked_start: set | None = None,
    locked_bench: set | None = None,
) -> tuple[tuple[int, int, int], list[dict]]:
    """
    Tries every legal formation against the fixed squad, returns the
    (formation, starting_xi) combination with the highest preference-adjusted
    score, honoring any manual start/bench locks.
    """
    locked_start = locked_start or set()
    locked_bench = locked_bench or set()

    gk = _position_pool(squad, scores, 1, locked_start, locked_bench)
    defs = _position_pool(squad, scores, 2, locked_start, locked_bench)
    mids = _position_pool(squad, scores, 3, locked_start, locked_bench)
    fwds = _position_pool(squad, scores, 4, locked_start, locked_bench)

    best_adjusted_total = -1.0
    best_formation = None
    best_xi = None

    for d, m, f in LEGAL_FORMATIONS:
        if len(defs) < d or len(mids) < m or len(fwds) < f or len(gk) < 1:
            continue
        xi = gk[:1] + defs[:d] + mids[:m] + fwds[:f]
        raw_total = sum(scores.get(p["id"], 0) for p in xi)
        adjusted_total = raw_total * FORMATION_PREFERENCE.get((d, m, f), 1.0)
        if adjusted_total > best_adjusted_total:
            best_adjusted_total = adjusted_total
            best_formation = (d, m, f)
            best_xi = xi

    return best_formation, best_xi


def pick_captain_vice(starters: list[dict], ep_scores: dict) -> tuple[int, int]:
    outfield = [p for p in starters if p["element_type"] != 1]
    ranked = sorted(
        outfield,
        key=lambda p: -(ep_scores.get(p["id"], 0) * CAPTAINCY_CEILING_MULTIPLIER.get(p["element_type"], 1.0)),
    )
    return ranked[0]["id"], ranked[1]["id"]


def apply_stability_rule(
    new_xi_ids: set[int],
    previous_xi_ids: set[int],
    new_total_score: float,
    previous_total_score: float,
) -> bool:
    if not previous_xi_ids:
        return True
    if new_xi_ids == previous_xi_ids:
        return False
    improvement = new_total_score - previous_total_score
    return improvement >= STABILITY_THRESHOLD
