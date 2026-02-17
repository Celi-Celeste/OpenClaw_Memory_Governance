#!/usr/bin/env python3
"""Evaluate retrieval confidence and suggest transcript lookup when needed."""

from __future__ import annotations

import argparse
import json


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected true|false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--avg-similarity", type=float, required=True)
    parser.add_argument("--result-count", type=int, required=True)
    parser.add_argument("--retrieval-confidence", type=float, default=-1.0)
    parser.add_argument("--continuation-intent", type=parse_bool, required=True)
    parser.add_argument("--min-similarity", type=float, default=0.72)
    parser.add_argument("--min-results", type=int, default=5)
    parser.add_argument("--min-confidence", type=float, default=0.65)
    args = parser.parse_args()

    avg_similarity = clamp(args.avg_similarity)
    result_count = max(args.result_count, 0)
    retrieval_confidence = (
        avg_similarity
        if args.retrieval_confidence < 0
        else clamp(args.retrieval_confidence)
    )
    result_strength = clamp(result_count / max(args.min_results, 1))
    confidence_score = clamp((retrieval_confidence * 0.7) + (result_strength * 0.3))

    trigger_reasons = []
    if avg_similarity < args.min_similarity:
        trigger_reasons.append("weak_similarity")
    if result_count < args.min_results:
        trigger_reasons.append("sparse_results")
    if args.continuation_intent and confidence_score < args.min_confidence:
        trigger_reasons.append("continuation_gap")

    action = "respond_normally"
    suggested_prompt = ""
    if trigger_reasons:
        action = "partial_and_ask_lookup"
        suggested_prompt = (
            "I can give a safe partial answer from current memory. "
            "Do you want me to check transcript archives for specific details?"
        )

    payload = {
        "action": action,
        "confidence_score": round(confidence_score, 4),
        "trigger_reasons": trigger_reasons,
        "suggested_prompt": suggested_prompt,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
