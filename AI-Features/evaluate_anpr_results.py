"""Evaluate ANPR JSON results against exact normalized plate labels."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def normalize_plate(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def edit_distance(first: str, second: str) -> int:
    """Return Levenshtein distance using linear memory."""
    first, second = normalize_plate(first), normalize_plate(second)
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for row, left in enumerate(first, start=1):
        current = [row]
        for column, right in enumerate(second, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def best_predictions(results: list[dict[str, Any]]) -> dict[str, str]:
    """Select the highest-confidence non-empty reading for every image."""
    predictions: dict[str, str] = {}
    for item in results:
        image = str(item.get("image") or "")
        readings = [reading for reading in item.get("readings", []) if reading.get("plate")]
        if image and readings:
            best = max(readings, key=lambda reading: float(reading.get("ocr_confidence", 0.0)))
            predictions[image] = normalize_plate(str(best["plate"]))
    return predictions


def evaluate(results: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, float | int]:
    predictions = best_predictions(results)
    normalized_labels = {name: normalize_plate(plate) for name, plate in labels.items()}
    total = len(normalized_labels)
    exact = sum(predictions.get(name) == plate for name, plate in normalized_labels.items())
    distance = sum(
        edit_distance(predictions.get(name, ""), plate)
        for name, plate in normalized_labels.items()
    )
    characters = sum(len(plate) for plate in normalized_labels.values())
    return {
        "labelled_images": total,
        "predicted_images": sum(name in predictions for name in normalized_labels),
        "exact_matches": exact,
        "exact_plate_accuracy": exact / total if total else 0.0,
        "character_accuracy": max(0.0, 1.0 - distance / characters) if characters else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True, help="ANPR result JSON")
    parser.add_argument("--labels", type=Path, required=True, help="JSON object: image name to plate")
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if not isinstance(results, list) or not isinstance(labels, dict):
        raise ValueError("Results must be a list and labels must be a JSON object")
    print(json.dumps(evaluate(results, labels), indent=2))


if __name__ == "__main__":
    main()
