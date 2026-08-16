"""
Orchestrator. Invoked by GitHub Actions on a schedule (see
.github/workflows/scheduler.yml and .github/workflows/telegram-listener.yml).
Figures out what stage of the deadline cycle we're in and does the
appropriate thing — this is what lets a single frequent cron schedule handle
predicted/final/late-check messaging without a complex dynamic scheduler.
"""
import argparse
from datetime import datetime, timedelta, timezone

from . import fpl_api, filters, fixture_diff, scoring, squad_builder, lineup, state as state_mod
from . import news, telegram_bot, deadlines, review

MANUAL_REQUEST_BUFFER_MINUTES = 3  # if within this window of a scheduled run, defer to it instead


def run_build_squad(budget: float):
    bootstrap = fpl_api.get_bootstrap_static()
    fixtures = fpl_api.get_fixtures()
    elements = filters.filter_available_players(bootstrap["elements"])

    fav = fixture_diff.opportunity_teams  # noqa: F841 (available if needed for reporting)
    strengths = fixture_diff.team_strength_map(bootstrap)
    fixture_favorability = {}
    for p in elements:
        is_attacking_position = p["element_type"] in (3, 4)
        fixture_favorability[p["id"]] = fixture_diff.upcoming_fixture_run(
            p["team"], fixtures, strengths, attacking=is_attacking_position, n_gameweeks=5
        )

    scores = scoring.score_players(elements, fixture_favorability)
    ep_scores = scoring.raw_expected_points(elements)
    squad_ids = squad_builder.build_optimal_squad(elements, scores, budget=budget)

    by_id = {p["id"]: p for p in bootstrap["elements"]}
    squad_players = [by_id[pid] for pid in squad_ids]
    formation, starters = lineup.best_formation_and_xi(squad_players, scores)
    captain_id, vice_id = lineup.pick_captain_vice(starters, ep_scores)

    state = state_mod.load_state()
    state["squad"]["players"] = [
        {"id": p["id"], "name": p["web_name"], "element_type": p["element_type"], "team": p["team"],
         "price_bought": p["now_cost"] / 10.0}
        for p in squad_players
    ]
    spend = sum(p["now_cost"] / 10.0 for p in squad_players)


if __name__ == "__main__":
    main()
