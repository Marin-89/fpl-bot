"""
Daily news digest — free RSS feeds only, filtered to your squad's players so
you get signal, not the entire FPL internet. See README for why we don't do
open-ended web/forum scraping here (cost + ToS reasons discussed in spec).
"""
import feedparser

FEEDS = [
    "https://www.fantasyfootballscout.co.uk/feed/",
    "https://allaboutfpl.com/feed",
]


def fetch_recent_entries(max_per_feed: int = 20) -> list[dict]:
    entries = []
    for url in FEEDS:
        parsed = feedparser.parse(url)
        for entry in parsed.entries[:max_per_feed]:
            entries.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "source": url,
            })
    return entries


def filter_for_squad(entries: list[dict], squad_player_names: list[str]) -> list[dict]:
    """
    Keeps only entries that mention one of your squad's player surnames.
    Simple, free, deterministic — no LLM needed for this filtering step.
    """
    relevant = []
    lowered_names = [n.lower() for n in squad_player_names]
    for entry in entries:
        text = f"{entry['title']} {entry['summary']}".lower()
        matched = [name for name in lowered_names if name in text]
        if matched:
            relevant.append({**entry, "matched_players": matched})
    return relevant
