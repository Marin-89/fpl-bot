"""
Polls Telegram for new messages and handles the manual "lineup" command.
Runs frequently (see .github/workflows/listener.yml) since GitHub Actions
has no persistent always-on process to receive messages instantly — this
polling approach is the closest free, serverless equivalent. Expect a reply
within roughly the listener's poll interval (a few minutes), not instantly.
"""
import os
from datetime import datetime, timezone, timedelta

from . import telegram_bot, state as state_mod

LINEUP_KEYWORDS = {"lineup"}
SCHEDULED_INTERVAL_MINUTES = 30  # must match .github/workflows/scheduler.yml cron
WARNING_WINDOW_MINUTES = 3


def _next_scheduled_run(now: datetime) -> datetime:
    """Next top-of-hour or half-hour mark in UTC, matching the scheduler's */30 cron."""
    minute = 0 if now.minute < 30 else 30
    candidate = now.replace(minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(minutes=SCHEDULED_INTERVAL_MINUTES)
    return candidate


def poll_and_handle():
    state = state_mod.load_state()
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
            continue  # ignore messages from anyone but the configured user

        text = (message.get("text") or "").strip().lower()
        if text not in LINEUP_KEYWORDS:
            continue

        _handle_lineup_request()

    if highest_update_id is not None:
        state["telegram_offset"] = highest_update_id
        state_mod.save_state(state)


def _handle_lineup_request():
    current_state = state_mod.load_state()

    if current_state.get("processing"):
        telegram_bot.send_message("Lineup is currently being prepared. Please wait for the scheduled update.")
        return

    now = datetime.now(timezone.utc)
    next_run = _next_scheduled_run(now)
    minutes_until_next = (next_run - now).total_seconds() / 60.0
    if 0 < minutes_until_next <= WARNING_WINDOW_MINUTES:
        telegram_bot.send_message("Scheduled lineup will be sent shortly.")
        return

    from . import main as main_mod
    main_mod.run_manual_lineup()
