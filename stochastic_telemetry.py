import json
import math
from datetime import datetime, timezone

CACHE_PATH = "telemetry_cache.json"


def sample_std(values):
    """Return sample standard deviation for recent numeric observations, or None if < 2 points."""
    clean = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    variance = sum((x - mean) ** 2 for x in clean) / (len(clean) - 1)
    return round(math.sqrt(variance), 4)


def smooth_series(history, current_value, alpha=0.2):
    """
    Exponentially smoothed update:
        smoothed_t = alpha * current_t + (1 - alpha) * smoothed_{t-1}
    """
    if current_value is None:
        return history[-1] if history else None
    val = float(current_value)
    if not history:
        return round(val, 4)
    prev = float(history[-1])
    return round((alpha * val) + ((1.0 - alpha) * prev), 4)


def classify_regime(smoothed_score, volatility):
    """
    Assign a bounded analytical regime bucket ([Conceptual / Analytical Bucket]).
    Adjust thresholds to match your 0-100 scale or spread scale.
    """
    if smoothed_score is None:
        return "Unclassified / Stale"
    vol = volatility or 0.0
    if smoothed_score >= 70.0 or (smoothed_score >= 55.0 and vol >= 12.0):
        return "Acute Stress"
    if smoothed_score >= 40.0 or vol >= 6.0:
        return "Elevated Friction"
    return "Contained"


def update_signal_uncertainty(cache, signal_key, new_value, is_online=True, alpha=0.2, max_history=30):
    """
    Update a named telemetry stream with:
        - rolling observations (capped at max_history)
        - dispersion/volatility (sample standard deviation)
        - smoothed level ([Proxy / Estimate])
        - regime label ([Conceptual / Analytical Bucket])
        - explicit feed health / freshness status
    """
    streams = cache.setdefault("stochastic_streams", {})
    entry = streams.get(signal_key, {
        "history": [],
        "smoothed_history": [],
        "lineage_level": "Proxy / Estimate",
        "lineage_regime": "Conceptual / Analytical Bucket",
    })

    if is_online and new_value is not None:
        history = list(entry.get("history", []))
        history.append(float(new_value))
        history = history[-max_history:]

        smoothed_val = smooth_series(entry.get("smoothed_history", []), float(new_value), alpha=alpha)
        smoothed_hist = list(entry.get("smoothed_history", []))
        if smoothed_val is not None:
            smoothed_hist.append(smoothed_val)
        smoothed_hist = smoothed_hist[-max_history:]

        vol = sample_std(history[-10:])
        entry.update({
            "latest_raw": float(new_value),
            "history": history,
            "smoothed_value": smoothed_val,
            "smoothed_history": smoothed_hist,
            "volatility_std_10": vol,
            "regime": classify_regime(smoothed_val, vol),
            "status": "online",
            "alpha": alpha,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        # Never invent values when offline; preserve last valid state and mark stale/offline
        last_smoothed = entry.get("smoothed_value")
        last_vol = entry.get("volatility_std_10")
        entry.update({
            "status": "stale_or_offline",
            "regime": classify_regime(last_smoothed, last_vol),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        })

    streams[signal_key] = entry
    return entry


def update_stochastic_telemetry(cache_path=CACHE_PATH):
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {"timestamp": datetime.now(timezone.utc).isoformat(), "tracked_topics": []}

    # Example wiring: pull latest numeric values from existing cache sections if present
    # Replace/extend with your actual friction score, FX premium %, or discourse index
    fx_premium = cache.get("fx_premium_pct")
    friction_score = cache.get("avg_friction_score")

    update_signal_uncertainty(
        cache,
        signal_key="fx_spread_stress",
        new_value=fx_premium,
        is_online=(fx_premium is not None),
        alpha=0.2,
    )
    update_signal_uncertainty(
        cache,
        signal_key="legislative_friction",
        new_value=friction_score,
        is_online=(friction_score is not None),
        alpha=0.2,
    )

    cache["stochastic_updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print("Updated stochastic_streams in", cache_path)


if __name__ == "__main__":
    update_stochastic_telemetry()
