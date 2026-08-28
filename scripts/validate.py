#!/usr/bin/env python3
"""Validate reproduced LDP speedups against the archived reference results."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {row["task"]: row for row in csv.DictReader(stream)}


def read_stat(path: Path, name: str) -> float | None:
    if not path.exists():
        return None
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == name:
            try:
                return float(fields[1])
            except ValueError:
                return None
    return None


def geomean(values: list[float]) -> float:
    return math.prod(values) ** (1 / len(values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actual",
        type=Path,
        help="Observed CSV; defaults to results/<run-profile>/analysis/speedup.csv",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        help="Reference CSV; defaults to expected/<run-profile>/speedup.csv",
    )
    parser.add_argument(
        "--run-profile", choices=("fast", "full"), default="fast"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Stats root; defaults to results/<run-profile>",
    )
    parser.add_argument(
        "--relative-tolerance",
        type=float,
        default=0.05,
        help="Allowed relative speedup difference (default: 0.05)",
    )
    args = parser.parse_args()

    result_root = args.output_root or ROOT / "results" / args.run_profile
    actual_path = args.actual or result_root / "analysis" / "speedup.csv"
    actual = read_csv(actual_path.resolve())
    expected_path = args.expected or (
        ROOT / "expected" / args.run_profile / "speedup.csv"
    )
    expected = read_csv(expected_path.resolve())
    failures: list[str] = []
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        if missing:
            failures.append("missing task(s): " + ", ".join(missing))
        if extra:
            failures.append("unexpected task(s): " + ", ".join(extra))

    actual_speedups: list[float] = []
    expected_speedups: list[float] = []
    for task in sorted(expected):
        if task not in actual:
            continue
        try:
            observed = float(actual[task]["speedup_ldp_over_nopf"])
            reference = float(expected[task]["speedup_ldp_over_nopf"])
        except (KeyError, ValueError):
            failures.append(f"{task}: missing or invalid speedup")
            continue
        actual_speedups.append(observed)
        expected_speedups.append(reference)
        relative_error = abs(observed - reference) / reference
        if observed <= 1.0:
            failures.append(f"{task}: LDP speedup is not positive ({observed:.6f}x)")
        if relative_error > args.relative_tolerance:
            failures.append(
                f"{task}: {observed:.6f}x differs from "
                f"{reference:.6f}x by {relative_error:.2%}"
            )

        task_root = result_root.resolve() / task
        nopf_insts = read_stat(task_root / "stats_nopf_restored.txt", "simInsts")
        ldp_insts = read_stat(task_root / "stats_ldp_restored.txt", "simInsts")
        if nopf_insts is None or ldp_insts is None:
            failures.append(f"{task}: missing simInsts in paired stats")
        elif abs(nopf_insts - ldp_insts) > 10:
            failures.append(
                f"{task}: simulated instruction mismatch "
                f"({nopf_insts:g} vs {ldp_insts:g})"
            )

    if actual_speedups and len(actual_speedups) == len(expected_speedups):
        observed_overall = geomean(actual_speedups)
        expected_overall = geomean(expected_speedups)
        relative_error = abs(observed_overall - expected_overall) / expected_overall
        print(
            f"overall task-weighted geomean: {observed_overall:.6f}x "
            f"(reference {expected_overall:.6f}x)"
        )
        if relative_error > args.relative_tolerance:
            failures.append(
                "overall geomean differs from reference by "
                f"{relative_error:.2%}"
            )

    if failures:
        print("VALIDATION FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"VALIDATION PASSED: {len(expected)} task(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
