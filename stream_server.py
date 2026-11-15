import asyncio
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from aiohttp import web
from prescriptive_orientation import evaluate_orientation, evaluate_state_classification
from server import fetch_social_hashtag_trends

CONNECTED_CLIENTS = set()
LATEST_TRENDS = None
TREND_REFRESH_SECONDS = 60
LAYER2_MACRO_TTL_SECONDS = 6 * 60 * 60
LAYER2_MACRO_CACHE = {"expires_at": 0.0, "data": None}
logger = logging.getLogger("kuvhura.orientation")
TELEMETRY_TIMELINE = [
    {"date": "2026-11-08", "phi": 39.50, "markov_crisis_prob": 22.0, "state": "Latent Friction"},
    {"date": "2026-11-09", "phi": 38.10, "markov_crisis_prob": 24.5, "state": "Latent Friction"},
    {"date": "2026-11-10", "phi": 36.80, "markov_crisis_prob": 27.0, "state": "Latent Friction"},
    {"date": "2026-11-11", "phi": 34.20, "markov_crisis_prob": 31.0, "state": "Accelerated Degradation"},
    {"date": "2026-11-12", "phi": 30.50, "markov_crisis_prob": 38.0, "state": "Accelerated Degradation"},
    {"date": "2026-11-13", "phi": 27.90, "markov_crisis_prob": 42.5, "state": "Acute Crisis"},
    {"date": "2026-11-14", "phi": 24.15, "markov_crisis_prob": 46.8, "state": "Acute Systemic Crisis"},
]
for _seed, _macro_proxy in zip(TELEMETRY_TIMELINE, (45.0, 48.0, 50.0, 55.0, 60.0, 62.0, 65.0)):
    _seed["macro_volatility_proxy"] = _macro_proxy
    _seed["fsi"] = round(
        0.40 * (100.0 - _seed["phi"])
        + 0.35 * _seed["markov_crisis_prob"]
        + 0.25 * _macro_proxy,
        2,
    )
    _seed["warning_level"] = (
        "Stable Consolidation" if _seed["fsi"] <= 25
        else "Latent Friction" if _seed["fsi"] <= 50
        else "Accelerated Degradation" if _seed["fsi"] <= 75
        else "Acute Systemic Crisis"
    )
TIMELINE_BASELINE_DATE = None
TIMELINE_BASELINE = None
LATEST_DUAL_ENGINE_INPUTS = None
LATEST_FSI_INPUTS = None
MARKOV_TRANSITION_MATRIX = (
    (0.75, 0.20, 0.05),
    (0.15, 0.60, 0.25),
    (0.05, 0.30, 0.65),
)


def compute_bayesian_posterior(prior_phi, social_volume, engagement_score):
    """Update Φ with configured signal likelihoods; telemetry inputs are proxies."""
    for name, value in (
        ("prior_phi", prior_phi),
        ("social_volume", social_volume),
        ("engagement_score", engagement_score),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number.")
    if not 0 <= prior_phi <= 100:
        raise ValueError("prior_phi must be between 0 and 100.")
    if social_volume < 0 or engagement_score < 0:
        raise ValueError("social_volume and engagement_score must be non-negative.")

    prior_crisis_prob = 1.0 - prior_phi / 100.0
    is_high_stress = social_volume > 80 or engagement_score > 1200
    p_evidence_given_crisis = 0.82 if is_high_stress else 0.18
    p_evidence_given_stable = 0.25 if is_high_stress else 0.75
    p_evidence = (
        p_evidence_given_crisis * prior_crisis_prob
        + p_evidence_given_stable * (1 - prior_crisis_prob)
    )
    posterior_prob = p_evidence_given_crisis * prior_crisis_prob / p_evidence
    updated_phi = round((1.0 - posterior_prob) * 100, 2)
    return max(5.0, min(95.0, updated_phi))


def compute_markov_path_projection(last_crisis_prob):
    """Project one transition using the supplied three-state Markov matrix."""
    if (
        isinstance(last_crisis_prob, bool)
        or not isinstance(last_crisis_prob, (int, float))
        or not math.isfinite(last_crisis_prob)
        or not 0 <= last_crisis_prob <= 100
    ):
        raise ValueError("last_crisis_prob must be a finite percentage from 0 to 100.")

    current_state_vector = [
        max(0.0, 1.0 - last_crisis_prob / 50.0),
        0.5,
        min(1.0, last_crisis_prob / 100.0),
    ]
    total = sum(current_state_vector)
    current_state_vector = [state / total for state in current_state_vector]
    next_vector = [
        sum(
            current_state_vector[index] * MARKOV_TRANSITION_MATRIX[index][state]
            for index in range(3)
        )
        for state in range(3)
    ]
    return round(next_vector[2] * 100, 2)


def compute_fragility_state_index(phi, markov_crisis_prob, macro_volatility):
    """Compute FSI from normalized 0–100 inputs."""
    for name, value in (
        ("phi", phi),
        ("markov_crisis_prob", markov_crisis_prob),
        ("macro_volatility", macro_volatility),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 100
        ):
            raise ValueError(f"{name} must be a finite value between 0 and 100.")
    return round(
        0.40 * (100.0 - phi)
        + 0.35 * markov_crisis_prob
        + 0.25 * macro_volatility,
        2,
    )


def compute_macro_stress_proxy(layer2_macro):
    """Scale World Bank indicators to an experimental 0–100 macro-stress proxy."""
    if not isinstance(layer2_macro, dict) or layer2_macro.get("source") != "world_bank_v2":
        return None

    try:
        growth = float(layer2_macro["GDP_Growth"])
        inflation = float(layer2_macro["Inflation"])
        debt_gni = float(layer2_macro["Debt_GNI"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (growth, inflation, debt_gni)):
        return None

    inflation_stress = min(100.0, max(0.0, inflation / 2.0))
    debt_stress = min(100.0, max(0.0, debt_gni))
    growth_stress = min(100.0, max(0.0, (10.0 - growth) * 5.0))
    return round(
        0.50 * inflation_stress
        + 0.30 * debt_stress
        + 0.20 * growth_stress,
        2,
    )


def classify_fragility_state(fsi):
    if fsi <= 25:
        return "Stable Consolidation"
    if fsi <= 50:
        return "Latent Friction"
    if fsi <= 75:
        return "Accelerated Degradation"
    return "Acute Systemic Crisis"


def derive_social_metrics(payload):
    """Derive sampled-post volume and hashtag-mention activity from social telemetry."""
    if not payload.get("available") or payload.get("sampleType") == "rss-sheet":
        return None

    social_volume = payload.get("scannedPosts")
    if (
        isinstance(social_volume, bool)
        or not isinstance(social_volume, (int, float))
        or not math.isfinite(social_volume)
        or social_volume < 0
    ):
        raise ValueError("Social telemetry must provide a non-negative scannedPosts value.")

    hashtags = payload.get("hashtags")
    if not isinstance(hashtags, list):
        raise ValueError("Social telemetry hashtags must be a list.")
    engagement_score_proxy = 0
    for hashtag in hashtags:
        if not isinstance(hashtag, dict):
            raise ValueError("Social telemetry contains a malformed hashtag record.")
        mentions = hashtag.get("latestMentions", hashtag.get("mentions", 0))
        if (
            isinstance(mentions, bool)
            or not isinstance(mentions, (int, float))
            or not math.isfinite(mentions)
            or mentions < 0
        ):
            raise ValueError("Hashtag mention counts must be non-negative finite numbers.")
        engagement_score_proxy += mentions
    return social_volume, engagement_score_proxy


def _state_for_phi(phi):
    if phi > 60:
        return "Stable Consolidation"
    if phi > 35:
        return "Latent Friction"
    if phi > 20:
        return "Accelerated Degradation"
    return "Acute Systemic Crisis"


def update_telemetry_timeline(payload, evaluated_at=None, layer2_macro=None):
    """Update today's entry from one day's baseline and the latest social sample."""
    global LATEST_DUAL_ENGINE_INPUTS, LATEST_FSI_INPUTS, TELEMETRY_TIMELINE
    global TIMELINE_BASELINE, TIMELINE_BASELINE_DATE

    metrics = derive_social_metrics(payload)
    if metrics is None:
        return

    evaluated_at = evaluated_at or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    today = evaluated_at.astimezone(timezone.utc).date().isoformat()

    if TIMELINE_BASELINE_DATE != today:
        baseline_index = -2 if TELEMETRY_TIMELINE[-1]["date"] == today and len(TELEMETRY_TIMELINE) > 1 else -1
        baseline = TELEMETRY_TIMELINE[baseline_index]
        TIMELINE_BASELINE = {
            "phi": baseline["phi"],
            "markov_crisis_prob": baseline["markov_crisis_prob"],
        }
        TIMELINE_BASELINE_DATE = today

    prior = TIMELINE_BASELINE
    if prior is None:
        raise RuntimeError("The daily Markov/Bayesian baseline was not initialized.")
    social_volume, engagement_score_proxy = metrics
    current_phi = compute_bayesian_posterior(
        prior["phi"], social_volume, engagement_score_proxy
    )
    projected_crisis_prob = compute_markov_path_projection(
        prior["markov_crisis_prob"]
    )
    macro_stress_proxy = compute_macro_stress_proxy(layer2_macro)
    entry = {
        "date": today,
        "phi": current_phi,
        "markov_crisis_prob": projected_crisis_prob,
        "state": _state_for_phi(current_phi),
        "social_volume": social_volume,
        "engagement_score_proxy": engagement_score_proxy,
        "telemetry_source": payload.get("source", "social telemetry"),
        "updated_at": evaluated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if macro_stress_proxy is not None:
        entry["macro_volatility_proxy"] = macro_stress_proxy
        entry["fsi"] = compute_fragility_state_index(
            current_phi, projected_crisis_prob, macro_stress_proxy
        )
        entry["warning_level"] = classify_fragility_state(entry["fsi"])
        LATEST_FSI_INPUTS = {
            "status": "available",
            "macro_stress_proxy": macro_stress_proxy,
            "macro_source": layer2_macro["source"],
            "updated_at": entry["updated_at"],
        }
    else:
        LATEST_FSI_INPUTS = {
            "status": "awaiting_sourced_macro_data",
            "macro_stress_proxy": None,
            "macro_source": layer2_macro.get("source") if isinstance(layer2_macro, dict) else None,
            "updated_at": entry["updated_at"],
        }

    if TELEMETRY_TIMELINE[-1]["date"] == today:
        TELEMETRY_TIMELINE[-1] = entry
    else:
        TELEMETRY_TIMELINE.append(entry)
        if len(TELEMETRY_TIMELINE) > 14:
            TELEMETRY_TIMELINE.pop(0)
    LATEST_DUAL_ENGINE_INPUTS = {
        "social_volume": social_volume,
        "engagement_score_proxy": engagement_score_proxy,
        "telemetry_source": entry["telemetry_source"],
        "updated_at": entry["updated_at"],
    }


def get_dual_engine_timeline():
    return {
        "timeline": [dict(entry) for entry in TELEMETRY_TIMELINE],
        "engines": {
            "bayesian_status": "Active (sampled-post and hashtag-mention proxies)",
            "markov_status": "Active (three-state transition matrix)",
            "fsi_status": (
                "Active (World Bank macro-stress proxy)"
                if LATEST_FSI_INPUTS and LATEST_FSI_INPUTS["status"] == "available"
                else "Awaiting sourced World Bank macro data"
            ),
        },
        "inputStatus": "updated" if LATEST_DUAL_ENGINE_INPUTS else "awaiting_social_sample",
        "latestInputs": dict(LATEST_DUAL_ENGINE_INPUTS) if LATEST_DUAL_ENGINE_INPUTS else None,
        "fsiStatus": (
            dict(LATEST_FSI_INPUTS)
            if LATEST_FSI_INPUTS
            else {"status": "awaiting_sourced_macro_data", "macro_stress_proxy": None}
        ),
        "historyNote": (
            "Seed timeline values are illustrative. Live FSI uses 40% inverse Φ, 35% "
            "Markov crisis projection, and 25% macro-stress proxy. The proxy uses "
            "50% capped inflation/2, 30% capped debt-to-GNI, and 20% capped "
            "(10 minus GDP growth) times 5; these experimental scales are not calibrated."
        ),
    }


def fetch_layer2_macro_telemetry(use_cache=True):
    """Fetch Layer 2 macroeconomic indicators for Zimbabwe (ZWE) with baseline fallback."""
    now = time.monotonic()
    if use_cache and LAYER2_MACRO_CACHE["data"] is not None and LAYER2_MACRO_CACHE["expires_at"] > now:
        return LAYER2_MACRO_CACHE["data"]

    indicators = {
        "GDP_Growth": "NY.GDP.MKTP.KD.ZG",
        "Inflation": "FP.CPI.TOTL.ZG",
        "Debt_GNI": "DT.DOD.DECT.GN.ZS",
    }
    fallback_values = {"GDP_Growth": 8.3, "Inflation": 5.2, "Debt_GNI": 37.9}
    layer2_telemetry = {}
    used_fallback = False

    for key, ind_code in indicators.items():
        url = f"https://api.worldbank.org/v2/country/ZWE/indicator/{ind_code}?format=json&mrv=1"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KUVHURA-Observatory/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            if isinstance(response_data, list) and len(response_data) > 1 and response_data[1]:
                latest_val = response_data[1][0].get("value")
                if latest_val is not None:
                    layer2_telemetry[key] = float(latest_val)
                    continue
            layer2_telemetry[key] = fallback_values[key]
            used_fallback = True
        except Exception as error:
            print(f"Warning: Could not fetch Layer 2 indicator {key}: {error}")
            layer2_telemetry[key] = fallback_values[key]
            used_fallback = True

    layer2_telemetry["source"] = "fallback_baseline" if used_fallback else "world_bank_v2"
    print("Layer 2 Macro Telemetry Synchronized:", layer2_telemetry)
    LAYER2_MACRO_CACHE["data"] = layer2_telemetry
    LAYER2_MACRO_CACHE["expires_at"] = now + (300 if used_fallback else LAYER2_MACRO_TTL_SECONDS)
    return layer2_telemetry


async def register(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client connected ({len(CONNECTED_CLIENTS)} total)")
    if LATEST_TRENDS is not None:
        await websocket.send_json(LATEST_TRENDS)
    else:
        await websocket.send_json({
            "type": "stream_status",
            "status": "loading",
            "message": "Waiting for the first Zimbabwe trending telemetry snapshot.",
        })


async def unregister(websocket):
    CONNECTED_CLIENTS.discard(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client disconnected ({len(CONNECTED_CLIENTS)} remaining)")


def fetch_trending_telemetry():
    payload = fetch_social_hashtag_trends()
    if not isinstance(payload, dict) or not isinstance(payload.get("hashtags"), list):
        raise ValueError("Social telemetry endpoint returned an unexpected response")

    layer2_macro = fetch_layer2_macro_telemetry()
    update_telemetry_timeline(payload, layer2_macro=layer2_macro)
    updated_at = payload.get("updatedAt") or datetime.now(timezone.utc).isoformat()
    orientation = evaluate_orientation(payload)
    state_classification = evaluate_state_classification(payload.get("orientationInputs"))
    return {
        "type": "trending_telemetry",
        "status": "available" if payload.get("available") else "no_sources",
        "updatedAt": updated_at,
        "telemetry": payload,
        "orientation": orientation,
        "stateClassification": state_classification,
        "layer2Macro": layer2_macro,
        "dualEngineTimeline": get_dual_engine_timeline(),
        **({"message": payload["message"]} if payload.get("message") else {}),
    }


async def broadcast(packet):
    for websocket in tuple(CONNECTED_CLIENTS):
        if websocket.closed:
            await unregister(websocket)
            continue
        try:
            await websocket.send_json(packet)
        except (ConnectionResetError, RuntimeError) as error:
            print(f"Telemetry delivery failed; removing disconnected client: {error}")
            await unregister(websocket)


async def refresh_trending_telemetry():
    global LATEST_TRENDS
    while True:
        try:
            LATEST_TRENDS = await asyncio.to_thread(fetch_trending_telemetry)
            print(
                f"Zimbabwe trending telemetry refreshed at "
                f"{LATEST_TRENDS['updatedAt']} ({LATEST_TRENDS['status']})"
            )
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            LATEST_TRENDS = {
                "type": "trending_telemetry",
                "status": "error",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "message": f"Zimbabwe trending telemetry could not be loaded: {error}",
                "telemetry": None,
                "orientation": evaluate_orientation({}),
                "stateClassification": evaluate_state_classification(None),
            }
            print(LATEST_TRENDS["message"])

        logger.info("orientation_evaluation %s", json.dumps(LATEST_TRENDS["orientation"], separators=(",", ":")))
        logger.info(
            "state_classification %s",
            json.dumps(LATEST_TRENDS["stateClassification"]["timelineLog"]
                       if LATEST_TRENDS["stateClassification"]["status"] == "evaluated"
                       else LATEST_TRENDS["stateClassification"], separators=(",", ":")),
        )
        await broadcast(LATEST_TRENDS)
        await asyncio.sleep(TREND_REFRESH_SECONDS)


async def health(_request):
    return web.Response(text="ok\n")


async def dual_engine_timeline(_request):
    return web.json_response(
        get_dual_engine_timeline(),
        headers={"Access-Control-Allow-Origin": "*"},
    )


async def live_endpoint(request):
    websocket = web.WebSocketResponse()
    if not websocket.can_prepare(request).ok:
        return await health(request)

    await websocket.prepare(request)
    try:
        await register(websocket)
        async for _message in websocket:
            pass
    finally:
        await unregister(websocket)
    return websocket


def create_app():
    app = web.Application()
    app.router.add_get("/api/timeline", dual_engine_timeline)
    app.router.add_route("*", "/", live_endpoint)
    app.router.add_route("*", "/health", health)
    return app


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = os.environ.get("STREAM_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("STREAM_PORT", "8765")))
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    trends_task = asyncio.create_task(refresh_trending_telemetry())
    try:
        print(f"KUVHURA telemetry and health server listening on {host}:{port}")
        await trends_task
    finally:
        trends_task.cancel()
        await asyncio.gather(trends_task, return_exceptions=True)
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForecast server stopped.")
