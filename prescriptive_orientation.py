"""Transparent heuristic for normalized strategic-orientation telemetry."""

import math
from datetime import datetime, timezone


INPUT_FIELDS = (
    "regime_durability_index",
    "realized_praxis_yield",
    "parallel_fx_premium",
    "coercive_load",
)

ORIENTATIONS = {
    "decentralized_mutual_aid": "Decentralized mutual aid",
    "structural_negotiation": "Structural negotiation",
    "defensive_consolidation": "Defensive consolidation",
}

STATE_THRESHOLDS = {
    "consolidated_captivity": {
        "name": "Consolidated Captivity State",
        "color": "#f87171",
        "threshold_phi": 70,
        "prescription": (
            "Prioritize institutional resilience, decentralized mutual aid, "
            "and long-term shadow infrastructure mapping."
        ),
    },
    "protracted_crisis": {
        "name": "Protracted Crisis / Fragile State",
        "color": "#f59e0b",
        "threshold_phi": 40,
        "prescription": (
            "Leverage parallel market inefficiencies; optimize resource "
            "distribution networks to mitigate local extraction shocks."
        ),
    },
    "acute_systemic_failure": {
        "name": "Acute Systemic Failure",
        "color": "#ef4444",
        "threshold_phi": 20,
        "prescription": (
            "Activate emergency civic defense postures; pivot immediately to "
            "survival-driven coordination and sovereign alternative asset rails."
        ),
    },
}


def evaluate_state_classification(inputs, evaluated_at=None):
    """Classify normalized Φ thresholds; CL is validated and retained as context."""
    timestamp = evaluated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    evaluated_at_text = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    required = ("regime_durability_index", "coercive_load")
    if not isinstance(inputs, dict):
        return {
            "status": "awaiting_inputs",
            "evaluatedAt": evaluated_at_text,
            "missingInputs": list(required),
            "message": "No live Φ and coercive-load inputs were provided; no state was classified.",
        }

    missing = [field for field in required if field not in inputs]
    if missing:
        return {
            "status": "awaiting_inputs",
            "evaluatedAt": evaluated_at_text,
            "missingInputs": missing,
            "message": "State classification inputs are incomplete; no state was classified.",
        }

    invalid = []
    for field in required:
        value = inputs[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid.append(field)
        elif not math.isfinite(value) or not 0 <= value <= 100:
            invalid.append(field)
    if invalid:
        return {
            "status": "invalid_inputs",
            "evaluatedAt": evaluated_at_text,
            "invalidInputs": invalid,
            "message": "Φ and coercive load must be finite normalized values from 0 to 100.",
        }

    phi = inputs["regime_durability_index"]
    if phi >= STATE_THRESHOLDS["consolidated_captivity"]["threshold_phi"]:
        state_key = "consolidated_captivity"
    elif phi >= STATE_THRESHOLDS["protracted_crisis"]["threshold_phi"]:
        state_key = "protracted_crisis"
    else:
        state_key = "acute_systemic_failure"

    state = STATE_THRESHOLDS[state_key]
    timeline_log = {
        "timestamp": evaluated_at_text,
        "phi": phi,
        "coerciveLoad": inputs["coercive_load"],
        "classifiedState": state["name"],
        "recommendedOrientation": state["prescription"],
    }
    return {
        "status": "evaluated",
        "evaluatedAt": evaluated_at_text,
        "stateKey": state_key,
        "state": state["name"],
        "color": state["color"],
        "prescription": state["prescription"],
        "phi": phi,
        "coerciveLoad": inputs["coercive_load"],
        "timelineLog": timeline_log,
        "method": "phi-threshold-v1",
        "message": "Prototype threshold classification; review assumptions before use.",
    }


def evaluate_orientation(packet, evaluated_at=None):
    """Evaluate packet.orientationInputs; abstain unless all normalized inputs are valid."""
    timestamp = evaluated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    evaluated_at_text = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    inputs = packet.get("orientationInputs") if isinstance(packet, dict) else None
    if inputs is None:
        return {
            "status": "awaiting_inputs",
            "evaluatedAt": evaluated_at_text,
            "missingInputs": list(INPUT_FIELDS),
            "message": "No live orientation inputs were provided; no orientation was selected.",
        }
    if not isinstance(inputs, dict):
        return {
            "status": "invalid_inputs",
            "evaluatedAt": evaluated_at_text,
            "invalidInputs": ["orientationInputs must be an object"],
            "message": "Orientation inputs are invalid; no orientation was selected.",
        }

    missing = [field for field in INPUT_FIELDS if field not in inputs]
    if missing:
        return {
            "status": "awaiting_inputs",
            "evaluatedAt": evaluated_at_text,
            "missingInputs": missing,
            "message": "Orientation inputs are incomplete; no orientation was selected.",
        }

    invalid = []
    for field in INPUT_FIELDS:
        value = inputs[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid.append(field)
        elif not math.isfinite(value) or not 0 <= value <= 100:
            invalid.append(field)
    if invalid:
        return {
            "status": "invalid_inputs",
            "evaluatedAt": evaluated_at_text,
            "invalidInputs": invalid,
            "message": "Inputs must be finite normalized values from 0 to 100; no orientation was selected.",
        }

    phi = inputs["regime_durability_index"]
    yield_value = inputs["realized_praxis_yield"]
    fx_premium = inputs["parallel_fx_premium"]
    coercive_load = inputs["coercive_load"]
    scores = {
        "decentralized_mutual_aid": round(
            0.20 * (100 - phi)
            + 0.30 * yield_value
            + 0.25 * fx_premium
            + 0.25 * (100 - coercive_load),
            1,
        ),
        "structural_negotiation": round(
            0.30 * phi
            + 0.20 * yield_value
            + 0.20 * (100 - fx_premium)
            + 0.30 * (100 - coercive_load),
            1,
        ),
        "defensive_consolidation": round(
            0.25 * (100 - phi)
            + 0.20 * (100 - yield_value)
            + 0.10 * fx_premium
            + 0.45 * coercive_load,
            1,
        ),
    }
    selected = max(scores, key=scores.get)
    return {
        "status": "evaluated",
        "evaluatedAt": evaluated_at_text,
        "selectedOrientation": selected,
        "label": ORIENTATIONS[selected],
        "orientationIndex": scores[selected],
        "scores": scores,
        "inputs": {field: inputs[field] for field in INPUT_FIELDS},
        "method": "heuristic-v1",
        "message": "Prototype heuristic output; review assumptions before using it.",
    }
