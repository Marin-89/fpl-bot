"""
Given a fixed 15-man squad, picks the best starting XI + bench order for
THIS gameweek, applies the stability rule against the previously sent
lineup, and labels every player with an exact tactical position.

This is what runs daily — squad_builder.py only runs once, at Gameweek 1
(or when a high-conviction transfer is made).
"""

LEGAL_FORMATIONS = [
    (3, 4, 3), (3, 5, 2), (4, 4, 2), (4, 3, 3),
    (4, 5, 1), (5, 4, 1), (5, 3, 2), (5, 2, 3),
]

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
    4: 1.15,  # FWD — highest upside/ceiling, favored most for captaincy
    3: 1.08,  # MID
    2: 1.00,  # DEF — solid average, but lower ceiling than attackers
}


def label_positions(starters: list[dict], formation: tuple[int, int, int]) -> list[dict]:
    """
    starters: list of player dicts (must include 'element_type' and 'web_name'),
    already sorted GK, DEF..., MID..., FWD... in squad order.
    Returns the same players annotated with a 'tactical_position' label.
    """
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


def best_formation_and_xi(squad: list[dict], scores: dict) -> tuple[tuple[int, int, int], list[dict]]:
    """
    Tries every legal formation against the fixed squad, returns the
    (formation, starting_xi) combination with the highest total score.
    Uses the position-normalized 'scores' — correct here, since we're
    comparing e.g. defender vs defender for a starting slot, not captaincy.
    """
    gk = sorted([p for p in squad if p["element_type"] == 1], key=lambda p: -scores.get(p["id"], 0))
    defs = sorted([p for p in squad if p["element_type"] == 2], key=lambda p: -scores.get(p["id"], 0))
    mids = sorted([p for p in squad if p["element_type"] == 3], key=lambda p: -scores.get(p["id"], 0))
    fwds = sorted([p for p in squad if p["element_type"] == 4], key=lambda p: -scores.get(p["id"], 0))

    best_total = -1.0
    best_formation = None
    best_xi = None

    for d, m, f in LEGAL_FORMATIONS:
        if len(defs) < d or len(mids) < m or len(fwds) < f:
            continue
        xi = gk[:1] + defs[:d] + mids[:m] + fwds[:f]
        total = sum(scores.get(p["id"], 0) for p in xi)
        if total > best_total:
            best_total = total
            best_formation = (d, m, f)
            best_xi = xi

    return best_formation, best_xi


def pick_captain_vice(starters: list[dict], ep_scores: dict) -> tuple[int, int]:
    """
    Captain and vice-captain are chosen by raw expected points (ep_scores —
    see scoring.raw_expected_points), which is comparable across ALL
    positions, not the position-normalized 'scores' used elsewhere in this
    file. Goalkeepers are excluded entirely: even on a fair expected-points
    scale, a keeper's realistic ceiling in a single game is far below an
    attacker's, so they're never the right captain pick in practice.

    Among outfield players, a captaincy-specific ceiling multiplier is
    applied on top of raw expected points: attackers > midfielders >
    defenders. This reflects that captaincy value isn't just about average
    expected points — it's about upside. A defender and a forward can have
    similar average output, but the forward's spike potential (brace +
    assist + bonus) is much higher, which matters specifically because the
    armband doubles whatever happens. The multiplier nudges the choice
    toward that reality without rigidly overriding a genuinely large
    expected-points gap in a defender's favor.
    """
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
    """
    Returns True if the change is worth making (recommend it), False if the
    improvement is too marginal and we should hold the previous lineup.
    Only meaningful when previous_xi_ids is non-empty (i.e. not GW1).
    """
    if not previous_xi_ids:
        return True
    if new_xi_ids == previous_xi_ids:
        return False
    improvement = new_total_score - previous_total_score
    return improvement >= STABILITY_THRESHOLD
