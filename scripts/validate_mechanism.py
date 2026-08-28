#!/usr/bin/env python3
"""Validate loop-decoupling mechanism metrics against reference results."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METRICS = ("coverage", "timeliness", "speedup_over_nopf")


def read_rows(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {
            (row["application"], row["variant"]): row
            for row in csv.DictReader(stream)
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actual",
        type=Path,
        help=(
            "Observed CSV; defaults to "
            "results/<run-profile>/analysis/mechanism_summary.csv"
        ),
    )
    parser.add_argument(
        "--expected",
        type=Path,
        help=(
            "Reference CSV; defaults to "
            "expected/<run-profile>/mechanism_summary.csv"
        ),
    )
    parser.add_argument(
        "--run-profile", choices=("fast", "full"), default="fast"
    )
    parser.add_argument(
        "--relative-tolerance",
        type=float,
        default=0.05,
    )
    parser.add_argument(
        "--absolute-tolerance",
        type=float,
        default=0.005,
        help="Absolute tolerance used for reference values near zero",
    )
    args = parser.parse_args()

    actual_path = args.actual or (
        ROOT
        / "results"
        / args.run_profile
        / "analysis"
        / "mechanism_summary.csv"
    )
    actual = read_rows(actual_path.resolve())
    expected_path = args.expected or (
        ROOT / "expected" / args.run_profile / "mechanism_summary.csv"
    )
    expected = read_rows(expected_path.resolve())
    failures: list[str] = []
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            failures.append(f"missing rows: {missing}")
        if extra:
            failures.append(f"unexpected rows: {extra}")

    for key in sorted(set(actual) & set(expected)):
        for metric in METRICS:
            try:
                observed = float(actual[key][metric])
                reference = float(expected[key][metric])
            except (KeyError, ValueError):
                failures.append(f"{key}: invalid {metric}")
                continue
            allowed = max(
                args.absolute_tolerance,
                abs(reference) * args.relative_tolerance,
            )
            if abs(observed - reference) > allowed:
                failures.append(
                    f"{key} {metric}: {observed:.6f} differs from "
                    f"{reference:.6f} by more than {allowed:.6f}"
                )

    for application in sorted(
        {key[0] for key in expected if key[0] != "overall"}
    ):
        full = actual.get((application, "full"))
        no_loop = actual.get((application, "no_loop"))
        if not full or not no_loop:
            continue
        for metric in METRICS:
            if float(full[metric]) + args.absolute_tolerance < float(
                no_loop[metric]
            ):
                failures.append(
                    f"{application}: full LDP has lower {metric} than no-loop"
                )

    if failures:
        print("MECHANISM REPRODUCTION FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"MECHANISM REPRODUCTION PASSED: {len(expected)} summary rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
