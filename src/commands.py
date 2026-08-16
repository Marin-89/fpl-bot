"""
Registry of Telegram commands the bot understands. Adding a new command
later means adding one entry here — the listener's two-phase ack/process
flow (see telegram_listener.py) applies automatically to anything
registered, no new plumbing needed per command.
"""

# keyword -> (display name used in the "Got it" acknowledgment, function name in main.py to call)
COMMANDS = {
    "lineup": {
        "display_name": "your lineup",
        "handler": "run_manual_lineup",
    },
    # Future commands slot in here, e.g.:
    # "review": {"display_name": "your latest review", "handler": "run_manual_review"},
    # "chips": {"display_name": "chip status", "handler": "run_manual_chip_status"},
}


def match_command(text: str) -> str | None:
    """Returns the matched command keyword, or None if the text isn't a known command."""
    normalized = text.strip().lower()
    return normalized if normalized in COMMANDS else None
