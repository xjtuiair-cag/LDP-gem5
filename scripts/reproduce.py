#!/usr/bin/env python3
"""Run and validate the complete LDP artifact workflow with one command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run(command: list[str]) -> None:
    print("[WORKFLOW] " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-profile", choices=("fast", "full"), default="fast")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--gem5", type=Path)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()

    in_container = ROOT == Path("/opt/ldp")
    gem5 = args.gem5 or (
        Path("/opt/ldp/bin/gem5.opt")
        if in_container
        else ROOT / "build" / "ARM_LDP" / "gem5.opt"
    )
    checkpoint_root = args.checkpoint_root
    if checkpoint_root is None and in_container:
        checkpoint_root = Path("/opt/ldp/checkpoints")
    output_root = args.output_root or (
        Path("/results") / args.run_profile
        if in_container
        else ROOT / "results" / args.run_profile
    )

    run_command = [
        sys.executable,
        str(SCRIPTS / "run.py"),
        "--gem5",
        str(gem5),
        "--outdir",
        str(output_root),
        "--jobs",
        str(args.jobs),
        "--run-profile",
        args.run_profile,
        "--mechanism-ablation",
    ]
    if checkpoint_root is not None:
        run_command.extend(["--checkpoint-root", str(checkpoint_root)])
    if args.skip_existing:
        run_command.append("--skip-existing")
    if args.collect_only:
        run_command.append("--collect-only")
    run(run_command)

    expected_root = ROOT / "expected" / args.run_profile
    run(
        [
            sys.executable,
            str(SCRIPTS / "validate.py"),
            "--run-profile",
            args.run_profile,
            "--actual",
            str(output_root / "analysis" / "speedup.csv"),
            "--expected",
            str(expected_root / "speedup.csv"),
            "--output-root",
            str(output_root),
        ]
    )
    run(
        [
            sys.executable,
            str(SCRIPTS / "validate_mechanism.py"),
            "--run-profile",
            args.run_profile,
            "--actual",
            str(output_root / "analysis" / "mechanism_summary.csv"),
            "--expected",
            str(expected_root / "mechanism_summary.csv"),
        ]
    )

    print(
        "[RESULT] The representative subset reproduces the Fig. 18 "
        "performance direction and trend.",
        flush=True,
    )
    print(
        "[RESULT] Fig. 24-style loop-decoupling plot: "
        f"{output_root / 'analysis' / 'mechanism.png'}",
        flush=True,
    )
    print(f"[RESULT] Detailed results: {output_root / 'analysis'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(
            f"[WORKFLOW] FAILED: command exited with status {error.returncode}",
            file=sys.stderr,
        )
        raise SystemExit(error.returncode) from error
