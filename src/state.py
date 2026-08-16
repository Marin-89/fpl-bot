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
        "free_hit_1": {"used": False, "gameweek": None},
        "free_hit_2": {"used": False, "gameweek": None},
        "bench_boost_1": {"used": False, "gameweek": None},
        "bench_boost_2": {"used": False, "gameweek": None},
        "triple_captain_1": {"used": False, "gameweek": None},
        "triple_captain_2": {"used": False, "gameweek": None},
    },
    "free_transfers": 1,
    "last_processed_gameweek": None,
    "transfer_history": [],
    "live_message": {
        "gameweek": None,
        "message_id": None,
        "text": None,
    },
    "last_known_deadline": {
        "gameweek": None,
        "deadline_time": None,
        "first_kickoff": None,
    },
    "chip_expiry_warned": [],
    "chip_check_last_date": None,
    "captain_ep_history": [],
    "pending_command": None,
    "gameweek_history": [],
    "processing": False,
    "telegram_offset": None,
    "last_updated": None,
}


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return json.loads(json.dumps(DEFAULT_STATE))
    with open(STATE_PATH, "r") as f:
        loaded = json.load(f)
    merged = json.loads(json.dumps(DEFAULT_STATE))
    merged.update(loaded)
    for key in (
        "live_message", "last_known_deadline", "chips", "chip_expiry_warned",
        "last_processed_gameweek", "chip_check_last_date", "captain_ep_history",
        "pending_command",
    ):
        if key not in loaded:
            merged[key] = DEFAULT_STATE[key]
    return merged


def save_state(state: dict) -> None:
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
