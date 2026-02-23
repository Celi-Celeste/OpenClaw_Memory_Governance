#!/usr/bin/env python3
"""Execute confidence gate and optional transcript lookup as one deterministic flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from confidence_gate import evaluate_confidence_gate, parse_bool
from memory_lib import DEFAULT_TRANSCRIPT_ROOT
from transcript_lookup import lookup_transcripts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenClaw workspace root.")
    parser.add_argument("--topic", default="", help="Transcript lookup topic when lookup is approved.")
    parser.add_argument("--lookup-approved", type=parse_bool, default=False)

    parser.add_argument("--avg-similarity", type=float, required=True)
    parser.add_argument("--result-count", type=int, required=True)
    parser.add_argument("--retrieval-confidence", type=float, default=-1.0)
    parser.add_argument("--continuation-intent", type=parse_bool, required=True)
    parser.add_argument("--min-similarity", type=float, default=0.72)
    parser.add_argument("--min-results", type=int, default=5)
    parser.add_argument("--min-confidence", type=float, default=0.65)

    parser.add_argument("--transcript-root", default=DEFAULT_TRANSCRIPT_ROOT)
    parser.add_argument("--last-n-days", type=int, default=7)
    parser.add_argument("--max-excerpts", type=int, default=5)
    parser.add_argument("--max-chars-per-excerpt", type=int, default=1200)
    parser.add_argument("--allow-external-transcript-root", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    gate = evaluate_confidence_gate(
        avg_similarity=args.avg_similarity,
        result_count=args.result_count,
        retrieval_confidence=args.retrieval_confidence,
        continuation_intent=args.continuation_intent,
        min_similarity=args.min_similarity,
        min_results=args.min_results,
        min_confidence=args.min_confidence,
    )

    payload = {
        "decision": gate["action"],
        "gate": gate,
        "lookup_performed": False,
        "lookup": None,
        "message_to_user": "",
    }

    if gate["action"] == "respond_normally":
        print(json.dumps(payload, indent=2))
        return 0

    payload["decision"] = "partial_and_ask_lookup"
    payload["message_to_user"] = gate.get("suggested_prompt", "")
    if not args.lookup_approved:
        print(json.dumps(payload, indent=2))
        return 0

    topic = args.topic.strip()
    if not topic:
        raise SystemExit("Topic is required when --lookup-approved true.")

    lookup = lookup_transcripts(
        workspace=workspace,
        transcript_root=args.transcript_root,
        topic=topic,
        last_n_days=args.last_n_days,
        max_excerpts=args.max_excerpts,
        max_chars_per_excerpt=args.max_chars_per_excerpt,
        allow_external_transcript_root=args.allow_external_transcript_root,
    )
    payload["decision"] = "lookup_performed"
    payload["lookup_performed"] = True
    payload["lookup"] = lookup
    payload["message_to_user"] = ""
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
