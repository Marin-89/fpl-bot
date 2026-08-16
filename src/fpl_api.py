"""
Thin client for the official (unofficial-but-public) FPL API.

No auth needed. FPL sometimes blocks requests that don't look like they
come from a browser, so we send a realistic User-Agent.
"""
import requests

BASE = "https://fantasy.premierleague.com/api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _get(path: str) -> dict:
    resp = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_bootstrap_static() -> dict:
    """Players, teams, gameweek (event) metadata, deadlines. The core dataset."""
    return _get("bootstrap-static/")


def get_fixtures(event: int | None = None) -> list[dict]:
    """All fixtures, or fixtures for a specific gameweek if event is given."""
    path = "fixtures/"
    if event is not None:
        path += f"?event={event}"
    return _get(path)


def get_element_summary(player_id: int) -> dict:
    """Per-player fixture history and upcoming fixtures."""
    return _get(f"element-summary/{player_id}/")


def get_live_gameweek(event: int) -> dict:
    """Live points for a gameweek in progress (for auto-sub / live tracking)."""
    return _get(f"event/{event}/live/")


def current_and_next_event(bootstrap: dict) -> tuple[dict | None, dict | None]:
    """
    Returns (current_event, next_event) dicts from bootstrap['events'].
    current = is_current True; next = is_next True.
    Either may be None (e.g. season not started, or season finished).
    """
    current = next((e for e in bootstrap["events"] if e.get("is_current")), None)
    nxt = next((e for e in bootstrap["events"] if e.get("is_next")), None)
    return current, nxt


def first_fixture_kickoff(fixtures_for_event: list[dict]):
    """Earliest kickoff_time among a gameweek's fixtures, as an ISO string, or None."""
    times = [f["kickoff_time"] for f in fixtures_for_event if f.get("kickoff_time")]
    return min(times) if times else None
