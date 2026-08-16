"""
Builds the initial 15-man squad from scratch (Gameweek 1) as a real
optimization problem, not a greedy "top scorers" list — budget and formation
constraints interact, so this needs a solver.

FPL squad rules (encoded here as the source of truth — see
https://fantasy.premierleague.com/en/help/rules):
  - 15 players total: 2 GK, 5 DEF, 5 MID, 3 FWD
  - Max 3 players from any one Premier League club
  - Total spend <= budget (default £100.0m)
"""
import pulp

SQUAD_REQUIREMENTS = {1: 2, 2: 5, 3: 5, 4: 3}
MAX_PER_CLUB = 3


def build_optimal_squad(
    elements: list[dict],
    scores: dict,
    budget: float = 100.0,
    bench_weight: float = 0.15,
) -> list[int]:
    """
    Returns a list of 15 player IDs forming the optimal squad under budget
    and formation constraints.

    bench_weight: how much bench players' scores count toward the objective
    (low but nonzero — we still want a competent bench, not just 11 good
    players and 4 throwaways, since bench strength was an explicit
    requirement).

    NOTE: this picks the 15-man SQUAD. Picking which 11 of those 15 start,
    with tactical position labels, is lineup.py's job (it runs against a
    fixed squad, gameweek to gameweek).
    """
    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)

    picked = {p["id"]: pulp.LpVariable(f"pick_{p['id']}", cat="Binary") for p in elements}
    starter = {p["id"]: pulp.LpVariable(f"start_{p['id']}", cat="Binary") for p in elements}

    by_id = {p["id"]: p for p in elements}

    prob += pulp.lpSum(
        scores.get(pid, 0) * (starter[pid] + bench_weight * (picked[pid] - starter[pid]))
        for pid in picked
    )

    for pid in picked:
        prob += starter[pid] <= picked[pid]

    prob += pulp.lpSum(starter.values()) == 11
    prob += pulp.lpSum(starter[pid] for pid in picked if by_id[pid]["element_type"] == 1) == 1
    prob += pulp.lpSum(starter[pid] for pid in picked if by_id[pid]["element_type"] == 2) >= 3
    prob += pulp.lpSum(starter[pid] for pid in picked if by_id[pid]["element_type"] == 3) >= 2
    prob += pulp.lpSum(starter[pid] for pid in picked if by_id[pid]["element_type"] == 4) >= 1

    for etype, count in SQUAD_REQUIREMENTS.items():
        prob += pulp.lpSum(
            picked[pid] for pid in picked if by_id[pid]["element_type"] == etype
        ) == count

    club_ids = {p["team"] for p in elements}
    for club in club_ids:
        prob += pulp.lpSum(
            picked[pid] for pid in picked if by_id[pid]["team"] == club
        ) <= MAX_PER_CLUB

    prob += pulp.lpSum(
        picked[pid] * (by_id[pid]["now_cost"] / 10.0) for pid in picked
    ) <= budget

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"Squad optimizer did not find an optimal solution: {pulp.LpStatus[prob.status]}")

    return [pid for pid, var in picked.items() if var.value() == 1]
