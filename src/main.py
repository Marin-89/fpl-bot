"""
Orchestrator. Invoked by GitHub Actions on a schedule (see
.github/workflows/scheduler.yml and .github/workflows/listener.yml).

Design: rather than sending a fresh Telegram message every time it runs,
the bot maintains ONE "live" message per gameweek that it silently edits
in place. A NEW message (an alert) is only sent when something actually
worth your attention happens: a material lineup change, entering the Final
Confirmed window, a detected FPL deadline/fixture reschedule, or a flagged
chip opportunity (checked once per day, not every scheduler tick).
"""
import argparse
from datetime import datetime, timezone

from . import fpl_api, filters, fixture_diff, scoring, squad_builder, lineup, state as state_mod
from . import news, telegram_bot, deadlines, review, telegram_listener, chips as chips_mod, transfers
from . import chip_opportunities


def run_build_squad(budget: float):
    bootstrap = fpl_api.get_bootstrap_static()
    fixtures = fpl_api.get_fixtures()
    elements = filters.filter_available_players(bootstrap["elements"])

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
         "price_bought": p["now_cost"] / 10.0, "sell_price": p["now_cost"] / 10.0}
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
    state["live_message"] = {"gameweek": None, "message_id": None, "text": None}
    state_mod.save_state(state)

    print(f"Squad built. Formation {state['squad']['formation']}, bank £{state['squad']['bank']}m")


def run_daily():
    state = state_mod.load_state()
    if not state["squad"]["players"]:
        print("No squad in state yet — run --mode build-squad first.")
        return

    state["processing"] = True
    state_mod.save_state(state)
    try:
        _run_daily_inner(state)
    finally:
        state = state_mod.load_state()
        state["processing"] = False
        state_mod.save_state(state)


def _run_daily_inner(state: dict):
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

    # --- Deadline/kickoff change detection: alert immediately if FPL moved something ---
    last_known = state.get("last_known_deadline", {})
    if (
        last_known.get("gameweek") == target_event["id"]
        and last_known.get("deadline_time") is not None
        and (last_known.get("deadline_time") != deadline_time or last_known.get("first_kickoff") != first_kickoff)
    ):
        telegram_bot.send_message(
            f"⚠️ *Gameweek {target_event['id']} schedule changed*\n\n"
            f"Deadline: {last_known.get('deadline_time')} → {deadline_time}\n"
            f"First kickoff: {last_known.get('first_kickoff')} → {first_kickoff}"
        )
    state["last_known_deadline"] = {
        "gameweek": target_event["id"], "deadline_time": deadline_time, "first_kickoff": first_kickoff,
    }

    # --- Free transfer accumulation for this gameweek ---
    transfers.advance_gameweek_free_transfers(state, target_event["id"])

    # --- Chip expiry warning (first-half chips expire at GW19, don't carry over) ---
    expiring = chips_mod.expiring_soon(state["chips"], target_event["id"])
    if expiring and target_event["id"] not in state.get("chip_expiry_warned", []):
        chip_names = ", ".join(k.replace("_1", "").replace("_", " ").title() for k in expiring)
        telegram_bot.send_message(
            f"⏳ *Chip expiry warning*\n\n"
            f"Unused first-half chip(s) — {chip_names} — expire at the GW{chips_mod.FIRST_HALF_DEADLINE_EVENT} "
            f"deadline and will NOT carry over. Consider using them before then."
        )
        state.setdefault("chip_expiry_warned", []).append(target_event["id"])

    now = datetime.now(timezone.utc)
    stage = deadlines.current_stage(now, deadline_time, first_kickoff)
    if stage == "locked":
        print("Deadline has passed for this gameweek. Nothing to do.")
        state_mod.save_state(state)
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

    # --- Sell price update for every squad player, using current market price ---
    for p in state["squad"]["players"]:
        live = by_id.get(p["id"])
        if live:
            p["sell_price"] = transfers.calculate_sell_price(p["price_bought"], live["now_cost"] / 10.0)

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
    bench_players = [
        {**p, "_group": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[p["element_type"]]}
        for p in bench_players
    ]

    # --- Daily chip opportunity check (once per calendar day, not every scheduler tick) ---
    today_str = now.date().isoformat()
    if state.get("chip_check_last_date") != today_str:
        budget_estimate = state["squad"]["bank"] + sum(
            p.get("sell_price", p["price_bought"]) for p in state["squad"]["players"]
        )
        opportunity_messages = chip_opportunities.run_daily_chip_check(
            state, bootstrap, elements, all_fixtures, scores, ep_scores,
            target_event["id"], squad_players, final_starters, bench_players,
            captain_id, budget_estimate,
        )
        if opportunity_messages:
            telegram_bot.send_message("*Chip opportunity check*\n\n" + "\n\n".join(opportunity_messages))
        state["chip_check_last_date"] = today_str

    changes = []
    material_change = should_change and previous_xi_ids and new_xi_ids != previous_xi_ids
    if material_change:
        added = new_xi_ids - previous_xi_ids
        removed = previous_xi_ids - new_xi_ids
        for pid in removed:
            in_name = by_id.get(list(added)[0], {}).get("web_name", "?") if added else "?"
            changes.append(f"{by_id[pid]['web_name']} → {in_name}: score improved beyond stability threshold")

    stage_display = {
        "predicted": "Predicted Lineup",
        "final_window": "Final Confirmed Lineup",
        "late_check_window": "Late Update",
    }[stage]

    captain_name = by_id[captain_id]["web_name"]
    vice_name = by_id[vice_id]["web_name"]
    message_text = telegram_bot.format_lineup_message(
        stage_display, target_event["id"], labeled, bench_players, captain_name, vice_name, changes
    )

    live_msg = state.get("live_message", {})
    is_new_gameweek = live_msg.get("gameweek") != target_event["id"]
    text_unchanged = (not is_new_gameweek) and live_msg.get("text") == message_text

    entering_final_window_now = stage == "final_window" and live_msg.get("_last_stage") != "final_window"
    should_alert = material_change or entering_final_window_now or (stage == "late_check_window" and changes)

    if is_new_gameweek or not live_msg.get("message_id"):
        message_id = telegram_bot.send_message(message_text)
        state["live_message"] = {"gameweek": target_event["id"], "message_id": message_id, "text": message_text}
        print(f"Sent new live message for GW{target_event['id']} (stage: {stage_display})")
    elif not text_unchanged:
        edited = telegram_bot.edit_message(live_msg["message_id"], message_text)
        state["live_message"]["text"] = message_text
        if edited:
            print(f"Edited live message for GW{target_event['id']} (stage: {stage_display})")
        else:
            print("Edit failed (likely stale message_id) — sending a fresh message instead.")
            message_id = telegram_bot.send_message(message_text)
            state["live_message"] = {"gameweek": target_event["id"], "message_id": message_id, "text": message_text}
    else:
        print("No change since last check — live message left as-is.")

    state["live_message"]["_last_stage"] = stage

    if should_alert:
        alert_reason = (
            "Lineup changed" if material_change
            else "Final Confirmed Lineup is now locked in" if entering_final_window_now
            else "Late change detected before deadline"
        )
        telegram_bot.send_message(f"🔔 *{alert_reason}* — see the updated lineup above.")
        print(f"Sent alert: {alert_reason}")

    state["squad"]["starting_xi_ids"] = list(new_xi_ids) if should_change else list(previous_xi_ids)
    state["squad"]["bench_ids"] = bench_ids
    state["squad"]["captain_id"] = captain_id
    state["squad"]["vice_captain_id"] = vice_id
    state["squad"]["formation"] = "-".join(str(x) for x in final_formation)
    state_mod.save_state(state)


def run_manual_lineup():
    """
    On-demand lineup, triggered by typing 'lineup' in Telegram (see
    telegram_listener.py) or by running this mode directly. Unlike
    run_daily, this always computes and sends the current lineup regardless
    of deadline stage or whether an identical message was already sent —
    it's an explicit request, so the usual silence-on-no-change rule
    doesn't apply here.
    """
    state = state_mod.load_state()
    if not state["squad"]["players"]:
        telegram_bot.send_message("No squad found yet — run Build Initial Squad first.")
        return

    state["processing"] = True
    state_mod.save_state(state)
    telegram_bot.send_message("Working on it...")

    try:
        bootstrap = fpl_api.get_bootstrap_static()
        current_event, next_event = fpl_api.current_and_next_event(bootstrap)
        target_event = next_event or current_event
        if not target_event:
            telegram_bot.send_message("No upcoming or current gameweek found (season likely finished).")
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
        captain_id, vice_id = lineup.pick_captain_vice(starters, ep_scores)
        labeled = lineup.label_positions(starters, formation)
        for p in labeled:
            p["_group"] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[p["element_type"]]

        starter_ids = {p["id"] for p in starters}
        bench_ids = [pid for pid in squad_ids if pid not in starter_ids]
        bench_players = [by_id[pid] for pid in bench_ids if pid in by_id]
        bench_players = [
            {**p, "_group": {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}[p["element_type"]]}
            for p in bench_players
        ]

        captain_name = by_id[captain_id]["web_name"]
        vice_name = by_id[vice_id]["web_name"]
        message = telegram_bot.format_lineup_message(
            "Lineup (Manual Request)", target_event["id"], labeled, bench_players,
            captain_name, vice_name, changes=None,
        )
        telegram_bot.send_message(message)

        state["squad"]["starting_xi_ids"] = list(starter_ids)
        state["squad"]["bench_ids"] = bench_ids
        state["squad"]["captain_id"] = captain_id
        state["squad"]["vice_captain_id"] = vice_id
        state["squad"]["formation"] = "-".join(str(x) for x in formation)
    finally:
        state["processing"] = False
        state_mod.save_state(state)


def _formation_from_ids(xi_ids, by_id):
    counts = {2: 0, 3: 0, 4: 0}
    for pid in xi_ids:
        et = by_id[pid]["element_type"]
        if et in counts:
            counts[et] += 1
    return (counts[2], counts[3], counts[4])


def run_review(gameweek: int):
    state = state_mod.load_state()
    fixtures_for_event = fpl_api.get_fixtures(event=gameweek)

    locked, message = review.gameweek_points_locked(fixtures_for_event)
    if not locked:
        telegram_bot.send_message(f"Gameweek {gameweek} review isn't ready yet: {message}")
        print(f"Review skipped: {message}")
        return

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
    parser.add_argument("--mode", required=True, choices=["build-squad", "daily", "review", "listen"])
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
    elif args.mode == "listen":
        telegram_listener.poll_and_handle()


if __name__ == "__main__":
    main()
