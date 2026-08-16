"""
The bot's memory: squad, bank, chips, transfer history, past predictions.
Stored as a single JSON file, committed back to the repo by the GitHub Action
after every run. This is what makes the bot "remember" across runs without
needing a database or paid hosting.
"""
import json
import os
from datetime import datetime, timezone

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "state.json")

DEFAULT_STATE = {
    "squad": {
        "players": [],
        "bank": 0.0,
        "formation": None,
        "starting_xi_ids": [],
        "bench_ids": [],
        "captain_id": None,
        "vice_captain_id": None,
    },
    "chips": {
        "wildcard_1": {"used": False, "gameweek": None},
        "wildcard_2": {"used": False, "gameweek": None},
        "free_hit": {"used": False, "gameweek": None},
        "bench_boost": {"used": False, "gameweek": None},
        "triple_captain": {"used": False, "gameweek": None},
    },
    "free_transfers": 1,
    "transfer_history": [],
    "last_lineup_sent": {
        "gameweek": None,
        "stage": None,
        "xi_ids": [],
    },
    "gameweek_history": [],
    "processing": False,       # true while a lineup computation is in progress — used by
                                # telegram_listener.py to answer "is it currently running?"
    "telegram_offset": None,   # Telegram getUpdates offset, so the listener never re-processes
                                # the same incoming message twice
    "last_updated": None,
}


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return json.loads(json.dumps(DEFAULT_STATE))  # deep copy
    with open(STATE_PATH, "r") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
