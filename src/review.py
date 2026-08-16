"""
Post-gameweek review: logs predicted vs actual points automatically (free,
deterministic). Deeper strategic review ("was this the right call, what
should we learn") happens in a weekly chat with Claude, using this log as
the input — see README.
"""


def log_gameweek_result(
    state: dict,
    gameweek: int,
    predicted_points: float,
    actual_points: float,
    captain_id: int,
    captain_actual_points: int,
    notes: str = "",
) -> dict:
    entry = {
        "gameweek": gameweek,
        "predicted_points": predicted_points,
        "actual_points": actual_points,
        "error": actual_points - predicted_points,
        "captain_id": captain_id,
        "captain_actual_points": captain_actual_points,
        "notes": notes,
    }
    state["gameweek_history"].append(entry)
    return state


def backtest_weight_signal(history: list[dict]) -> dict:
    """
    Very simple accuracy tracking over time: mean absolute error and whether
    the model has been over- or under-predicting recently. This is the
    "real, bounded adaptation" piece — it doesn't rewrite the model on its
    own, but gives concrete numbers to discuss (and adjust weights from) in
    the weekly review.
    """
    if not history:
        return {"mean_abs_error": None, "bias": None, "n_gameweeks": 0}

    errors = [h["error"] for h in history]
    mean_abs_error = sum(abs(e) for e in errors) / len(errors)
    bias = sum(errors) / len(errors)
    return {
        "mean_abs_error": round(mean_abs_error, 2),
        "bias": round(bias, 2),
        "n_gameweeks": len(history),
    }
