#!/usr/bin/env python3
"""
main.py
────────
CLI entry point for the Itanta AI Agent Orchestrator.

Usage
-----
    # Interactive mode (answers questions in terminal)
    python main.py --project "My REST API" --spec spec.txt

    # Non-interactive mode with answers file
    python main.py --project "My REST API" --spec spec.txt --answers answers.json

    # Auto-approve all checkpoints (demo / CI mode)
    python main.py --project "My REST API" --spec spec.txt --auto-approve

Environment
-----------
    GEMINI_API_KEY   (required) — your Google Gemini API key
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="itanta-orchestrator",
        description="Itanta AI Agent Hackathon 2026 — Core Orchestrator",
    )
    parser.add_argument(
        "--project", "-p",
        required=True,
        help="Human-readable project name (e.g. 'My REST API')",
    )
    parser.add_argument(
        "--spec", "-s",
        required=True,
        help="Path to a text file containing the natural-language specification",
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--answers", "-a",
        default=None,
        help=(
            "Path to a JSON file mapping question → answer strings. "
            "If omitted, questions are asked interactively in the terminal."
        ),
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        default=False,
        help="Auto-approve all human checkpoints (useful for demos / CI).",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="./generated_project",
        help="Directory where the generated project will be written (default: ./generated_project)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── Validate environment ──────────────────────────────────
    if not os.environ.get("GEMINI_API_KEY"):
        print(
            "ERROR: GEMINI_API_KEY environment variable is not set.\n"
            "       Export it before running:  export GEMINI_API_KEY=your_key_here",
            file=sys.stderr,
        )
        sys.exit(1)

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"ERROR: Specification file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    # ── Load spec ─────────────────────────────────────────────
    raw_spec = spec_path.read_text(encoding="utf-8").strip()
    if not raw_spec:
        print("ERROR: Specification file is empty.", file=sys.stderr)
        sys.exit(1)

    # ── Build interaction callbacks ───────────────────────────
    pre_loaded_answers: dict = {}
    if args.answers:
        answers_path = Path(args.answers)
        if not answers_path.exists():
            print(f"ERROR: Answers file not found: {answers_path}", file=sys.stderr)
            sys.exit(1)
        with open(answers_path, encoding="utf-8") as fh:
            pre_loaded_answers = json.load(fh)

    def answer_fn(questions: list) -> dict:
        if pre_loaded_answers:
            # Return pre-loaded answers; fall back to default text for missing ones
            return {q: pre_loaded_answers.get(q, "No specific requirement.") for q in questions}
        # Interactive fallback
        print("\n── Clarifying Questions ──────────────────────────────────────")
        answers = {}
        for q in questions:
            print(f"\n  {q}")
            answers[q] = input("  Your answer: ").strip() or "No specific requirement."
        return answers

    def approval_fn(trigger: str, payload) -> bool:
        if args.auto_approve:
            print(f"[AUTO-APPROVE] Checkpoint: {trigger}")
            return True
        print(f"\n── Human Checkpoint: {trigger.upper()} ──────────────────────────")
        if hasattr(payload, "model_dump"):
            try:
                print(json.dumps(payload.model_dump(), indent=2, default=str)[:3000])
            except Exception:
                print(str(payload)[:1000])
        elif hasattr(payload, "diff_text"):
            print(payload.diff_text[:3000])
        answer = input("\n  Approve? [y/N]: ").strip().lower()
        return answer in ("y", "yes")

    # ── Build and run orchestrator ────────────────────────────
    from orchestrator.core import Orchestrator   # deferred import so env check runs first

    print(f"\n{'='*60}")
    print(f"  Itanta AI Agent Hackathon 2026 — Team Intent")
    print(f"  Project: {args.project}")
    print(f"  Config:  {config_path}")
    print(f"  Output:  {args.output_dir}")
    print(f"{'='*60}\n")

    orchestrator = Orchestrator.from_config(
        config_path=str(config_path),
        project_dir=args.output_dir,
    )

    summary = orchestrator.run(
        project_name=args.project,
        raw_input=raw_spec,
        answer_fn=answer_fn,
        approval_fn=approval_fn,
    )

    # ── Print final summary ───────────────────────────────────
    print(f"\n{'='*60}")
    print("  WORKFLOW COMPLETE")
    print(f"{'='*60}")
    print(f"  Status:         {summary.get('final_stage', 'unknown').upper()}")
    print(f"  Tasks completed:{summary['tasks']['completed']} / {summary['tasks']['total']}")
    print(f"  Tests passed:   {summary['tests']['passed']} / {summary['tests']['total']}  ({summary['tests']['pass_rate']})")
    print(f"  Files generated:{summary['files_generated']}")
    print(f"  API calls:      {summary['api_calls_total']}")
    print(f"  Duration:       {summary['duration_seconds']}s")
    print(f"\n  Reports written to ./logs/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
