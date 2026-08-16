"""
Builds the initial 15-man squad from scratch (Gameweek 1) as a real
optimization problem, not a greedy "top scorers" list — budget and formation
constraints interact, so this needs a solver.

FPL squad rules (encoded here as the source of truth — see
https://fantasy.premierleague.com/en/help/rules):
  - 15 players total: 2 GK, 5 DEF, 5 MID, 3 FWD
  - Max 3 players from any one Premier League club
  - Total spend <= budget (default £100.0m)

Additional soft guardrails (not FPL rules, our own design choice — see spec
discussion on formation strategy): DEFCON has made strong defenders
genuinely valuable, but an optimizer maximizing raw score can over-invest in
defenders and leave forwards under-funded, producing lopsided squads (e.g.
5 strong defenders + 3 budget-tier forwards) that force weak formations like
5-4-1. Two guardrails prevent that:
  - max_def_budget_fraction: caps total spend on defenders as a share of budget
  - min_avg_fwd_price: ensures forwards aren't all bottom-tier budget picks
"""
import pulp

SQUAD_REQUIREMENTS = {1: 2, 2: 5, 3: 5, 4: 3}
MAX_PER_CLUB = 3


def build_optimal_squad(
    elements: list[dict],
    scores: dict,
    budget: float = 100.0,
    bench_weight: float = 0.15,
    max_def_budget_fraction: float = 0.30,
    min_avg_fwd_price: float = 5.5,
) -> list[int]:
    """
    Returns a list of 15 player IDs forming the optimal squad under budget
    and formation constraints.

    bench_weight: how much bench players' scores count toward the objective
    (low but nonzero — we still want a competent bench, not just 11 good
    players and 4 throwaways, since bench strength was an explicit
    requirement).

    max_def_budget_fraction: defenders' total price cannot exceed this share
    of the budget (default 30%, above the ~25-26% top-50-manager average
    from FPL Review's Top 50 Strategy data, to leave headroom without
    forcing it — this discourages but doesn't ban a defender-heavy build).

    min_avg_fwd_price: average price of the 3 forwards must be at least this
    (default £5.5m) — stops the optimizer funding a defender-heavy squad by
    dumping all 3 forward slots into rock-bottom £4.5m picks.

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

    # Guardrail: cap defender spend as a share of total budget.
    def_spend = pulp.lpSum(
        picked[pid] * (by_id[pid]["now_cost"] / 10.0)
        for pid in picked if by_id[pid]["element_type"] == 2
    )
    prob += def_spend <= max_def_budget_fraction * budget

    # Guardrail: forwards' average price must clear a quality floor.
    fwd_spend = pulp.lpSum(
        picked[pid] * (by_id[pid]["now_cost"] / 10.0)
        for pid in picked if by_id[pid]["element_type"] == 4
    )
    prob += fwd_spend >= min_avg_fwd_price * SQUAD_REQUIREMENTS[4]

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(
            f"Squad optimizer did not find an optimal solution: {pulp.LpStatus[prob.status]}. "
            f"Try relaxing max_def_budget_fraction or min_avg_fwd_price."
        )

    return [pid for pid, var in picked.items() if var.value() == 1]
