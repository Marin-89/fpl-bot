"""
Sell-price calculation and free-transfer accumulation, per official FPL
rules (https://fantasy.premierleague.com/en/help/rules):
  - If a player's price rises after purchase, you keep half the increase
    when selling, rounded DOWN to the nearest £0.1m. If the price falls or
    stays flat, you simply sell at the current price (no special penalty).
  - You get 1 free transfer per Gameweek after your first deadline. Unused
    free transfers roll over, capped at a maximum of 5 stored at once.
  - Wildcard/Free Hit do NOT consume or reset saved free transfers.
"""
import math

MAX_FREE_TRANSFERS = 5


def calculate_sell_price(price_bought: float, current_price: float) -> float:
    """
    Returns what you'd actually receive for selling this player right now.
    """
    if current_price <= price_bought:
        return round(current_price, 1)
    profit = current_price - price_bought
    half_profit_rounded_down = math.floor((profit / 2) * 10) / 10.0
    return round(price_bought + half_profit_rounded_down, 1)


def advance_gameweek_free_transfers(state: dict, new_gameweek: int, max_free: int = MAX_FREE_TRANSFERS) -> dict:
    """
    Call once per daily run with the current target gameweek. Adds 1 free
    transfer (capped at max_free) for each new gameweek that's passed since
    the last time this was called, then records the new gameweek so it
    doesn't double-count on repeated runs within the same gameweek.
    """
    last = state.get("last_processed_gameweek")
    if last is not None and new_gameweek > last:
        gained = new_gameweek - last
        state["free_transfers"] = min(max_free, state.get("free_transfers", 1) + gained)
    state["last_processed_gameweek"] = new_gameweek
    return state


def record_transfer(state: dict, gameweek: int, out_name: str, in_name: str, reason: str) -> dict:
    """
    Logs a transfer and consumes a free transfer if one is available,
    otherwise records it as a hit (-4 points). Does not touch chip logic —
    if a Wildcard/Free Hit is active, don't call this per-transfer at all,
    since those chips make transfers free regardless of the free_transfers
    counter (see chips.py docstring).
    """
    hit = state.get("free_transfers", 0) <= 0
    if not hit:
        state["free_transfers"] -= 1

    state["transfer_history"].append({
        "gameweek": gameweek, "out": out_name, "in": in_name, "hit": hit, "reason": reason,
    })
    return state
