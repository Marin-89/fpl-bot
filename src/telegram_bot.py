"""
Sends and receives messages via the Telegram Bot API. Token and chat ID
come from environment variables (GitHub Secrets in production) — never
hardcoded.
"""
import os
import requests

API_BASE = "https://api.telegram.org"


def send_message(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set as environment variables."
        )

    resp = requests.post(
        f"{API_BASE}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("ok", False)


def get_updates(offset: int = 0) -> list[dict]:
    """
    Fetches new incoming messages since the given update offset (an
    incrementing ID Telegram assigns to every update — passing offset =
    last_seen_id + 1 tells Telegram "only give me updates after this one",
    so we don't reprocess the same message twice across runs).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set as an environment variable.")

    resp = requests.get(
        f"{API_BASE}/bot{token}/getUpdates",
        params={"offset": offset, "timeout": 0},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", [])


def format_lineup_message(
    stage_label: str,
    gameweek: int,
    labeled_starters: list[dict],
    bench: list[dict],
    captain_name: str,
    vice_name: str,
    changes: list[str] | None = None,
) -> str:
    lines = [f"*{stage_label} – Week {gameweek}*", ""]

    for group, header in [("GK", "Goalkeeper"), ("DEF", "Defence"), ("MID", "Midfield"), ("FWD", "Attack")]:
        group_players = [p for p in labeled_starters if p.get("_group") == group]
        if not group_players:
            continue
        lines.append(f"*{header}*")
        for p in group_players:
            tag = " (C)" if p["web_name"] == captain_name else " (VC)" if p["web_name"] == vice_name else ""
            lines.append(f"{p['tactical_position']} — {p['web_name']}{tag}")
        lines.append("")

    lines.append("*Bench*")
    for i, p in enumerate(bench, start=1):
        label = p.get("_group", "?")
        lines.append(f"{i}. {label} — {p['web_name']}")
    lines.append("")

    if changes:
        lines.append("*What changed*")
        for c in changes:
            lines.append(f"- {c}")
    else:
        lines.append("_No changes from the previous lineup._")

    return "\n".join(lines)
