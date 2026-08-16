"""
Polls Telegram for new messages and handles any registered command (see
commands.py). Runs frequently (see .github/workflows/listener.yml) since
GitHub Actions has no persistent always-on process to receive messages
instantly.

Every command follows the same two-phase pattern rather than being
answered in a single run: phase 1 (this poll cycle) sends "Got it, working
on <command>..." and records which command is pending; phase 2 (the NEXT
poll cycle, ~5 min later) actually runs the command's handler and sends
the real result. Doing both in one run would put them only seconds apart
regardless of how fast the handler is, so splitting across two poll cycles
is what makes the acknowledgment mean something.
"""
import os
from datetime import datetime, timezone, timedelta

from . import telegram_bot, state as state_mod, commands

SCHEDULED_INTERVAL_MINUTES = 30  # must match .github/workflows/scheduler.yml cron
WARNING_WINDOW_MINUTES = 3


def _next_scheduled_run(now: datetime) -> datetime:
    minute = 0 if now.minute < 30 else 30
    candidate = now.replace(minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(minutes=SCHEDULED_INTERVAL_MINUTES)
    return candidate


def poll_and_handle():
    state = state_mod.load_state()

    # --- Phase 2 first: if a command was acknowledged last cycle, run its
    # actual handler now, before checking for new messages — so the gap
    # between "Got it..." and the real result is a full poll interval. ---
    pending = state.get("pending_command")
    if pending:
        state["pending_command"] = None
        state_mod.save_state(state)
        _run_handler(pending)
        state = state_mod.load_state()  # reload, since the handler saved its own changes

    # --- Phase 1: check for new incoming messages ---
    offset = state.get("telegram_offset")
    updates = telegram_bot.get_updates(offset)

    own_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    highest_update_id = offset

    for update in updates:
        update_id = update["update_id"]
        if highest_update_id is None or update_id >= highest_update_id:
            highest_update_id = update_id + 1

        message = update.get("message")
        if not message:
            continue
        chat_id = str(message.get("chat", {}).get("id", ""))
        if own_chat_id and chat_id != str(own_chat_id):
            continue

        text = (message.get("text") or "").strip()
        matched = commands.match_command(text)
        if matched:
            _handle_command_request(matched)

    if highest_update_id is not None:
        state = state_mod.load_state()
        state["telegram_offset"] = highest_update_id
        state_mod.save_state(state)


def _handle_command_request(command_key: str):
    current_state = state_mod.load_state()
    command_info = commands.COMMANDS[command_key]

    if current_state.get("processing"):
        telegram_bot.send_message("Lineup is currently being prepared. Please wait for the scheduled update.")
        return

    now = datetime.now(timezone.utc)
    next_run = _next_scheduled_run(now)
    minutes_until_next = (next_run - now).total_seconds() / 60.0
    if 0 < minutes_until_next <= WARNING_WINDOW_MINUTES:
        telegram_bot.send_message("Scheduled lineup will be sent shortly.")
        return

    telegram_bot.send_message(f"Got it — working on {command_info['display_name']}...")
    current_state["pending_command"] = command_key
    state_mod.save_state(current_state)


def _run_handler(command_key: str):
    command_info = commands.COMMANDS.get(command_key)
    if not command_info:
        return  # command was removed from the registry since it was queued — nothing to do
    from . import main as main_mod
    handler = getattr(main_mod, command_info["handler"])
    handler(send_acknowledgment=False)
