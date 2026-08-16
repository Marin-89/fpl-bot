"""
Orchestrator. Invoked by GitHub Actions on a schedule (see
.github/workflows/scheduler.yml). Figures out what stage of the deadline
cycle we're in and does the appropriate thing — this is what lets a single
frequent cron schedule handle predicted/final/late-check messaging without
a complex dynamic scheduler.
"""
import argparse
from datetime import datetime, timezone

from . import fpl_api, filters, fixture_diff, scoring, squad_builder, lineup, state as state_mod
from . import news, telegram_bot, deadlines, review


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
    state["squad"]["bank"] = round(budget - spend, 1)
    state["squad"]["formation"] = "-".join(str(x) for x in formation)
    state["squad"]["starting_xi_ids"] = [p["id"] for p in starters]
    bench = [p for p in squad_players if p["id"] not in {s["id"] for s in starters}]
    state["squad"]["bench_ids"] = [p["id"] for p in bench]
    state["squad"]["captain_id"] = captain_id
    state["squad"]["vice_captain_id"] = vice_id
    state_mod.save_state(state)

    print(f"Squad built. Formation {state['squad']['formation']}, bank £{state['squad']['bank']}m")
    print("Run again with --mode daily once the season starts.")


def run_daily():
    state = state_mod.load_state()
    if not state["squad"]["players"]:
        print("No squad in state yet — run --mode build-squad first.")
        return

    bootstrap = fpl_api.get_bootstrap_static()
    current_event, next_event = fpl_api.current_and_next_event(bootstrap)
    target_event = next_event or current_event
    if not target_event:
        print("No upcoming or current gameweek found (season likely finished).")
        return

    event_fixtures = fpl_api.get_fixtures(event=target_event["id"])
    first_kickoff = fpl_api.first_fixture_kickoff(event_fixtures)
    deadline_time = target_event["deadline_time"]

    if not first_kickoff:
        print(f"No fixtures found yet for GW{target_event['id']} — skipping this run.")
        return

    check = deadlines.sanity_check_deadline(deadline_time, first_kickoff)
    if not check["consistent"]:
        print(f"WARNING: deadline/kickoff mismatch of {check['diff_minutes']:.0f} min — verify manually.")

    now = datetime.now(timezone.utc)
    stage = deadlines.current_stage(now, deadline_time, first_kickoff)
    if stage == "locked":
        print("Deadline has passed for this gameweek. Nothing to do.")
        return

    elements = filters.filter_available_players(bootstrap["elements"])
    all_fixtures = fpl_api.get_fixtures()
    strengths = fixture_diff.team_strength_map(bootstrap)
    fixture_favorability = {
        p["id"]: fixture_diff.upcoming_fixture_run(
            p["team"], all_fixtures, strengths, attacking=(p["element_type"] in (3, 4)), n_gameweeks=5
        )
        for p in elements
    }
    scores = scoring.score_players(elements, fixture_favorability)
    ep_scores = scoring.raw_expected_points(elements)

    by_id = {p["id"]: p for p in bootstrap["elements"]}
    squad_ids = [pl["id"] for pl in state["squad"]["players"]]
    squad_players = [by_id[pid] for pid in squad_ids if pid in by_id]

    formation, starters = lineup.best_formation_and_xi(squad_players, scores)
    new_xi_ids = {p["id"] for p in starters}
    previous_xi_ids = set(state["squad"]["starting_xi_ids"])
    new_total = sum(scores.get(pid, 0) for pid in new_xi_ids)
    previous_total = sum(scores.get(pid, 0) for pid in previous_xi_ids)

    should_change = lineup.apply_stability_rule(new_xi_ids, previous_xi_ids, new_total, previous_total)
    final_starters = starters if should_change else [by_id[pid] for pid in previous_xi_ids if pid in by_id]
    final_formation = formation if should_change else _formation_from_ids(previous_xi_ids, by_id)

    captain_id, vice_id = lineup.pick_captain_vice(final_starters, ep_scores)
    labeled = lineup.label_positions(final_starters, final_formation)
    for p in labeled:
        p["_group"] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[p["element_type"]]

    bench_ids = [pid for pid in squad_ids if pid not in {p["id"] for p in final_starters}]
    bench_players = [by_id[pid] for pid in bench_ids if pid in by_id]
    # NEW: label bench players by position group too (GK/DEF/MID/FWD),
    # so the Telegram message shows e.g. "1. DEF — Guéhi" instead of just a name.
    bench_players = [
        {**p, "_group": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[p["element_type"]]}
        for p in bench_players
    ]

    changes = []
    if should_change and previous_xi_ids and new_xi_ids != previous_xi_ids:
        added = new_xi_ids - previous_xi_ids
        removed = previous_xi_ids - new_xi_ids
        for pid in removed:
            in_name = by_id.get(list(added)[0], {}).get("web_name", "?") if added else "?"
            changes.append(f"{by_id[pid]['web_name']} → {in_name}: score improved beyond stability threshold")

    already_sent = (
        state["last_lineup_sent"]["gameweek"] == target_event["id"]
        and state["last_lineup_sent"]["stage"] == stage
        and set(state["last_lineup_sent"]["xi_ids"]) == new_xi_ids
    )

    if stage == "late_check_window":
        if not changes and already_sent:
            print("Late check: no material change, staying silent as designed.")
            return
        if not changes:
            print("Late check: no material change since Final message. Staying silent.")
            return
        stage_label = "Late Update"
    elif stage == "final_window":
        if already_sent:
            print("Final message already sent for this gameweek. Skipping duplicate.")
            return
        stage_label = "Final Confirmed Lineup"
    else:
        if already_sent:
            print("Predicted lineup already sent and unchanged today. Skipping duplicate.")
            return
        stage_label = "Predicted Lineup"

    captain_name = by_id[captain_id]["web_name"]
    vice_name = by_id[vice_id]["web_name"]
    message = telegram_bot.format_lineup_message(
        stage_label, target_event["id"], labeled, bench_players, captain_name, vice_name, changes
    )
    telegram_bot.send_message(message)
    print(f"Sent: {stage_label} – Week {target_event['id']}")

    state["squad"]["starting_xi_ids"] = list(new_xi_ids) if should_change else list(previous_xi_ids)
    state["squad"]["bench_ids"] = bench_ids
    state["squad"]["captain_id"] = captain_id
    state["squad"]["vice_captain_id"] = vice_id
    state["squad"]["formation"] = "-".join(str(x) for x in final_formation)
    state["last_lineup_sent"] = {
        "gameweek": target_event["id"], "stage": stage, "xi_ids": list(new_xi_ids),
    }
    state_mod.save_state(state)


def _formation_from_ids(xi_ids, by_id):
    counts = {2: 0, 3: 0, 4: 0}
    for pid in xi_ids:
        et = by_id[pid]["element_type"]
        if et in counts:
            counts[et] += 1
    return (counts[2], counts[3], counts[4])


def run_review(gameweek: int):
    """Post-gameweek: logs predicted-vs-actual and pings Telegram that review is ready."""
    state = state_mod.load_state()
    bootstrap = fpl_api.get_bootstrap_static()
    live = fpl_api.get_live_gameweek(gameweek)
    live_by_id = {e["id"]: e["stats"]["total_points"] for e in live["elements"]}

    xi_ids = state["squad"]["starting_xi_ids"]
    actual_total = sum(live_by_id.get(pid, 0) for pid in xi_ids)
    captain_id = state["squad"]["captain_id"]
    captain_points = live_by_id.get(captain_id, 0)
    actual_total += captain_points

    predicted_total = state.get("_last_predicted_total", actual_total)

    state = review.log_gameweek_result(
        state, gameweek, predicted_total, actual_total, captain_id, captain_points
    )
    state_mod.save_state(state)

    backtest = review.backtest_weight_signal(state["gameweek_history"])
    telegram_bot.send_message(
        f"*Gameweek {gameweek} review is ready.*\n\n"
        f"Actual points: {actual_total}\n"
        f"Model mean absolute error so far: {backtest['mean_abs_error']}\n\n"
        f"Bring this up in a chat with Claude when you're ready to go through it."
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["build-squad", "daily", "review"])
    parser.add_argument("--budget", type=float, default=100.0)
    parser.add_argument("--gameweek", type=int)
    args = parser.parse_args()

    if args.mode == "build-squad":
        run_build_squad(args.budget)
    elif args.mode == "daily":
        run_daily()
    elif args.mode == "review":
        if not args.gameweek:
            raise SystemExit("--gameweek is required for --mode review")
        run_review(args.gameweek)


if __name__ == "__main__":
    main()
