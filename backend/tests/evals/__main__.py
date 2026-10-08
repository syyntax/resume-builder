"""Run the evals: ``python -m tests.evals`` from backend/ (``make evals``).

Without ``--live`` everything runs against the offline model, which checks the harness, not the AI: its output
is mechanical, the judge is skipped, and a scanned PDF can't be read. A live run calls the Claude API with
the key in EVAL_ANTHROPIC_API_KEY and costs money (roughly $1 per case on Opus); nothing else is used, so a
key in your shell or env file is never spent by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from tests.evals import cases as data
from tests.evals.harness import BASELINE_FILE, Options, log, markdown, run

KEY_VARIABLE = "EVAL_ANTHROPIC_API_KEY"
FAKE_KEY = "sk-ant-api03-offline-eval-0123456789abcdefWXYZ"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.evals", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help=f"call the Claude API with ${KEY_VARIABLE} (costs money)")
    parser.add_argument("--model", default="claude-opus-5-5", help="the model the app uses (default: %(default)s)")
    parser.add_argument("--judge-model", default="claude-opus-5-5", help="the judge's model (default: %(default)s)")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    parser.add_argument("--case", action="append", choices=[c.id for c in data.CASES], metavar="ID",
                        help="run only this case (repeatable)")
    parser.add_argument("--no-imports", action="store_true", help="skip the import documents")
    parser.add_argument("--out", type=Path, default=Path("eval-results"),
                        help="report directory (default: %(default)s)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="save this run's coverage scores as the baseline (live runs only)")
    args = parser.parse_args(argv)

    key = FAKE_KEY
    if args.live:
        key = os.environ.get(KEY_VARIABLE, "").strip()
        if not key:
            parser.error(f"--live needs an API key in {KEY_VARIABLE}")
    elif args.update_baseline:
        parser.error("--update-baseline needs --live: the offline model's coverage isn't a baseline")
    selected = [c for c in data.CASES if not args.case or c.id in args.case]
    options = Options(
        provider="anthropic" if args.live else "fake",
        api_key=key,
        model=args.model,
        judge_model=None if args.no_judge or not args.live else args.judge_model,
        cases=selected,
        imports=[] if args.no_imports else list(data.IMPORTS),
        baseline=json.loads(BASELINE_FILE.read_text()) if BASELINE_FILE.exists() else {},
    )
    if args.live:
        log(f"Live run: {len(selected)} cases and {len(options.imports)} imports on your API key. This costs money.")

    report = run(options)

    out = args.out / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    summary = report["summary"]
    if not args.live:
        log(f"Offline run finished. Report: {out / 'report.md'}\nThis checks the harness, not the AI: the offline "
            "model's output is mechanical, so its failures (pages, the scanned PDF) are expected.")
        return 0
    log(f"{'Passed' if summary['passed'] else 'FAILED'} (about ${summary['costUsd']:.2f}). Report: {out / 'report.md'}")
    for failure in summary["failed"]:
        log(f"  - {failure}")
    if args.update_baseline:
        scores = {c["id"]: c["coverage"] for c in report["cases"] if c.get("coverage") is not None}
        baseline = {**options.baseline, **scores}
        BASELINE_FILE.write_text(json.dumps(dict(sorted(baseline.items())), indent=2) + "\n", encoding="utf-8")
        log(f"Saved the coverage baseline for {len(report['cases'])} cases to {BASELINE_FILE}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
