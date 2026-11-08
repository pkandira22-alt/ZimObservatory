#!/usr/bin/env python3
"""Fetch public historical series and evaluate simple one-period-ahead forecasts."""

import datetime as dt
import json
import math
import urllib.error
import urllib.parse
import urllib.request


USER_AGENT = "KUVHURA-Observatory/1.0"
WORLD_BANK_BASE = "https://api.worldbank.org/v2"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF"
DATA_TIMEOUT_SECONDS = 30
ANNUAL_HOLDOUT = 10
MONTHLY_HOLDOUT = 24
ANNUAL_MIN_TRAIN = 15
MONTHLY_MIN_TRAIN = 60


def _request_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=DATA_TIMEOUT_SECONDS) as response:
        return json.load(response)


def _request_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=DATA_TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_world_bank_series(indicator):
    query = urllib.parse.urlencode({"format": "json", "per_page": 1000})
    url = f"{WORLD_BANK_BASE}/country/ZW/indicator/{indicator}?{query}"
    payload = _request_json(url)
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise ValueError(f"Unexpected World Bank response for {indicator}")

    observations = []
    for item in payload[1]:
        if item.get("value") is None:
            continue
        value = float(item["value"])
        if math.isfinite(value):
            observations.append((int(item["date"]), value))
    observations.sort(key=lambda item: item[0])
    if not observations:
        raise ValueError(f"World Bank returned no observations for {indicator}")
    return observations, payload[0].get("lastupdated")


def fetch_gold_monthly_series():
    query = urllib.parse.urlencode({"range": "10y", "interval": "1mo"})
    payload = _request_json(f"{YAHOO_CHART_URL}?{query}")
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"Yahoo Finance returned an error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo Finance returned no gold futures data")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_series = result.get("indicators", {}).get("quote") or [{}]
    quotes = quote_series[0] if quote_series else {}
    closes = quotes.get("close") or []
    observations = []
    for timestamp, value in zip(timestamps, closes):
        if value is not None and math.isfinite(float(value)):
            month = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).strftime("%Y-%m")
            observations.append((month, float(value)))
    if not observations:
        raise ValueError("Yahoo Finance returned no valid monthly gold prices")
    return observations


def _predict(history, method, horizon=1):
    if method == "last_value":
        return history[-1]
    if method == "mean_5":
        return sum(history[-5:]) / min(5, len(history))
    if method == "drift_5":
        width = min(5, len(history) - 1)
        if width < 1:
            return history[-1]
        annual_change = (history[-1] - history[-1 - width]) / width
        return history[-1] + annual_change * horizon
    if method == "seasonal_12":
        return history[-13] if len(history) >= 13 else history[-1]
    if method == "drift_12":
        if len(history) < 13:
            return history[-1]
        return history[-1] + (history[-1] - history[-13]) * (horizon / 12)
    raise ValueError(f"Unknown forecast method: {method}")


def _mae(pairs):
    if not pairs:
        return None
    return sum(abs(prediction - actual) for prediction, actual in pairs) / len(pairs)


def _rolling_backtest(values, methods, horizon, min_train, holdout_count):
    eligible_origins = list(range(min_train - 1, len(values) - horizon))
    test_count = min(holdout_count, max(0, len(eligible_origins) // 2))
    test_origins = eligible_origins[-test_count:] if test_count else []
    validation_origins = eligible_origins[:-test_count] if test_count else []
    if len(validation_origins) < 3 or len(test_origins) < 3:
        return {
            "status": "insufficient_history",
            "reason": "Not enough rolling-origin observations for separate model selection and holdout testing.",
            "validationForecasts": len(validation_origins),
            "holdoutForecasts": len(test_origins),
        }

    validation_errors = {}
    for method in methods:
        pairs = [
            (_predict(values[:origin + 1], method, horizon), values[origin + horizon])
            for origin in validation_origins
        ]
        validation_errors[method] = _mae(pairs)
    selected_method = min(validation_errors, key=validation_errors.get)

    holdout = {}
    for method in methods:
        pairs = [
            (_predict(values[:origin + 1], method, horizon), values[origin + horizon])
            for origin in test_origins
        ]
        holdout[method] = {
            "mae": _mae(pairs),
            "forecasts": len(pairs),
            "start": test_origins[0],
            "end": test_origins[-1],
        }

    naive_mae = holdout["last_value"]["mae"]
    selected_mae = holdout[selected_method]["mae"]
    skill = 0.0 if naive_mae == 0 else 1 - selected_mae / naive_mae
    beats_naive = selected_method != "last_value" and selected_mae < naive_mae
    return {
        "status": "skill_over_naive" if beats_naive else "no_skill_over_naive",
        "selectedMethod": selected_method,
        "validationMAE": validation_errors[selected_method],
        "holdoutMAE": selected_mae,
        "naiveHoldoutMAE": naive_mae,
        "skillVsNaive": skill,
        "beatsNaive": beats_naive,
        "validationForecasts": len(validation_origins),
        "holdoutForecasts": len(test_origins),
        "holdoutMethodMetrics": holdout,
        "holdoutOriginsOverlap": horizon > 1,
    }


def _unavailable_target(target, reason):
    return {"id": target, "status": "unavailable", "reason": reason}


def _forecast_annual_target(target_id, indicator, label, unit, now_year):
    values, source_updated = fetch_world_bank_series(indicator)
    years, observations = zip(*values)
    backtest = _rolling_backtest(
        list(observations),
        ("last_value", "mean_5", "drift_5"),
        horizon=1,
        min_train=ANNUAL_MIN_TRAIN,
        holdout_count=ANNUAL_HOLDOUT,
    )
    target = {
        "id": target_id,
        "label": label,
        "unit": unit,
        "source": f"World Bank indicator {indicator}",
        "sourceUrl": f"{WORLD_BANK_BASE}/country/ZW/indicator/{indicator}?format=json",
        "sourceUpdatedAt": source_updated,
        "observedThrough": years[-1],
        "backtest": backtest,
    }

    if target_id == "inflation" and now_year - years[-1] > 1:
        target.update({
            "status": "stale_data",
            "reason": (
                f"The latest World Bank inflation observation is {years[-1]}; "
                "it is too stale for a current forecast."
            ),
        })
        return target

    if len(observations) < ANNUAL_MIN_TRAIN + 6:
        target.update({
            "status": "insufficient_history",
            "reason": "Not enough dated observations for a separate rolling-origin holdout.",
        })
        return target

    benchmark = observations[-1]
    skill_passed = (
        backtest.get("status") == "skill_over_naive"
        and backtest.get("holdoutForecasts", 0) >= 5
    )
    target.update({
        "status": "validated_candidate" if skill_passed else "baseline_only",
        "forecast": {
            "period": years[-1] + 1,
            "value": _predict(list(observations), "last_value"),
            "method": "last-observation baseline",
        },
        "reason": None if skill_passed else (
            "No tested candidate reliably outperformed the last-observation benchmark "
            "on the held-out years; this value is a reference baseline, not a validated "
            "predictive model."
        ),
    })
    return target


def _forecast_gold_target():
    observations = fetch_gold_monthly_series()
    dates, values = zip(*observations)
    backtest = _rolling_backtest(
        list(values),
        ("last_value", "seasonal_12", "drift_12"),
        horizon=12,
        min_train=MONTHLY_MIN_TRAIN,
        holdout_count=MONTHLY_HOLDOUT,
    )
    last_month = dt.datetime.strptime(dates[-1], "%Y-%m").date()
    target_month = last_month.replace(year=last_month.year + 1, day=1)
    selected_method = backtest.get("selectedMethod", "last_value")
    skill_passed = (
        backtest.get("status") == "skill_over_naive"
        and backtest.get("holdoutForecasts", 0) >= 10
    )
    provisional = skill_passed and backtest.get("holdoutOriginsOverlap", False)
    forecast_method = selected_method if skill_passed else "last_value"
    target = {
        "id": "gold",
        "label": "Gold futures price (GC=F)",
        "unit": "USD per troy ounce",
        "source": "Yahoo Finance monthly gold futures closes",
        "sourceUrl": "https://finance.yahoo.com/quote/GC%3DF/",
        "observedThrough": dates[-1],
        "backtest": backtest,
        "status": (
            "provisional_candidate" if provisional
            else "validated_candidate" if skill_passed
            else "baseline_only"
        ),
        "forecast": {
            "period": target_month.strftime("%Y-%m"),
            "value": _predict(list(values), forecast_method, horizon=12),
            "method": forecast_method,
        },
    }
    if provisional:
        target["reason"] = (
            "The drift candidate improved holdout MAE over persistence, but the "
            "12-month-ahead test origins overlap. Treat this as provisional, not "
            "independently validated."
        )
    elif not skill_passed:
        target["reason"] = (
            "The selected one-year-ahead candidate did not beat the naive benchmark "
            "on the held-out window. The displayed value is a reference baseline, "
            "not a validated predictive model."
        )
    return target


def build_forecast_report():
    now = dt.datetime.now(dt.timezone.utc)
    targets = []

    for target_id, indicator, label, unit in (
        ("gdp", "NY.GDP.MKTP.KD.ZG", "Zimbabwe GDP growth", "% annual"),
        ("inflation", "FP.CPI.TOTL.ZG", "Zimbabwe consumer inflation", "% annual"),
    ):
        try:
            targets.append(
                _forecast_annual_target(target_id, indicator, label, unit, now.year)
            )
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            targets.append(_unavailable_target(target_id, f"Could not load historical data: {error}"))

    try:
        targets.append(_forecast_gold_target())
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
        targets.append(_unavailable_target("gold", f"Could not load historical data: {error}"))

    targets.extend([
        _unavailable_target(
            "protests",
            "No permissioned, dated Zimbabwe protest-event dataset is configured; media mentions are not event counts.",
        ),
        _unavailable_target(
            "phi",
            "Φ is a dashboard formula with unobserved, mostly fixed inputs; there is no historical outcome series to forecast or validate.",
        ),
        {
            "id": "other",
            "status": "not_requested",
            "reason": "No custom target was specified.",
        },
    ])
    return {
        "type": "forecast_report",
        "generatedAt": now.isoformat(timespec="seconds"),
        "horizon": "one annual observation for macro series; 12 months for gold",
        "methodology": (
            "Rolling-origin, one-step-ahead backtests. Candidate selection uses only "
            "earlier validation origins; final metrics use a later chronological holdout "
            "and compare against last-observation persistence. Overlapping gold horizons "
            "are not independent. A baseline forecast is not described as validated skill."
        ),
        "targets": targets,
    }


if __name__ == "__main__":
    print(json.dumps(build_forecast_report(), indent=2, allow_nan=False))
