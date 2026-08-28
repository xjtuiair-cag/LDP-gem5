#!/usr/bin/env python3
"""Collect and validate the loop-decoupling mechanism ablation."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFETCHER = "system.cpu.dcache.prefetcher."
DCACHE_MISSES = "system.cpu.dcache.demandMshrMisses::total"
VARIANTS = {
    "no_loop": "ldp_no_loop_restored",
    "full": "ldp_restored",
}
RAW_STATS = {
    "sim_seconds": "simSeconds",
    "sim_insts": "simInsts",
    "demand_mshr_misses": DCACHE_MISSES,
    "pf_issued": PREFETCHER + "pfIssued",
    "pf_late": PREFETCHER + "pfLate",
    "pf_useful": PREFETCHER + "pfUseful",
    "pf_unused": PREFETCHER + "pfUnused",
    "demand_hits_at_pf": PREFETCHER + "demandMshrHitsAtPf",
    "demand_hits_at_pf_alloc": PREFETCHER + "demandMshrHitsAtPfAlloc",
}


def application_name(task: str) -> str:
    if task.startswith("graph_"):
        for suffix in ("_cg10", "_ss"):
            if task.endswith(suffix):
                return task[: -len(suffix)]
    return task


def geomean(values: list[float]) -> float:
    return math.prod(values) ** (1 / len(values))


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else math.nan


def read_stats(path: Path) -> dict[str, float]:
    wanted = set(RAW_STATS.values())
    values: dict[str, float] = {}
    if not path.exists():
        return values
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] not in wanted:
            continue
        try:
            # gem5 may emit a second dump while terminating. The existing
            # artifact validator intentionally uses the first complete dump.
            values.setdefault(fields[0], float(fields[1]))
        except ValueError:
            continue
    return values


def stats_path(root: Path, task: str, config: str) -> Path:
    flat = root / task / f"stats_{config}.txt"
    if flat.exists():
        return flat
    return root / task / config / "stats.txt"


def task_metrics(
    root: Path,
    task: str,
) -> tuple[list[dict[str, object]], list[str]]:
    failures: list[str] = []
    nopf = read_stats(stats_path(root, task, "nopf_restored"))
    nopf_seconds = nopf.get("simSeconds")
    nopf_insts = nopf.get("simInsts")
    nopf_misses = nopf.get(DCACHE_MISSES)
    for name, value in (
        ("simSeconds", nopf_seconds),
        ("simInsts", nopf_insts),
        (DCACHE_MISSES, nopf_misses),
    ):
        if value is None:
            failures.append(f"{task}/nopf_restored: missing {name}")

    rows: list[dict[str, object]] = []
    for label, config in VARIANTS.items():
        stats = read_stats(stats_path(root, task, config))
        required = (
            "simSeconds",
            "simInsts",
            DCACHE_MISSES,
            PREFETCHER + "pfIssued",
        )
        missing = [
            stat_name
            for stat_name in required
            if stat_name not in stats
        ]
        if missing:
            failures.append(f"{task}/{config}: missing {', '.join(missing)}")
            continue
        for stat_name in RAW_STATS.values():
            stats.setdefault(stat_name, 0.0)
        sim_seconds = stats["simSeconds"]
        sim_insts = stats["simInsts"]
        misses = stats[DCACHE_MISSES]
        useful = stats[PREFETCHER + "pfUseful"]
        hits = stats[PREFETCHER + "demandMshrHitsAtPf"]
        hits_alloc = stats[PREFETCHER + "demandMshrHitsAtPfAlloc"]
        issued = stats[PREFETCHER + "pfIssued"]
        late = stats[PREFETCHER + "pfLate"]

        coverage = ratio(
            useful + hits,
            useful + hits + misses,
        )
        timeliness = (
            ratio(useful, useful + hits) if useful + hits > 0 else 0.0
        )
        speedup = (
            ratio(nopf_seconds, sim_seconds)
            if nopf_seconds is not None
            else math.nan
        )
        row: dict[str, object] = {
            "task": task,
            "application": application_name(task),
            "variant": label,
            "config": config,
            "simSeconds": f"{sim_seconds:.9f}",
            "simInsts": f"{sim_insts:.0f}",
            "nopf_demandMshrMisses": (
                f"{nopf_misses:.0f}" if nopf_misses is not None else ""
            ),
            "demandMshrMisses": f"{misses:.0f}",
            "pfIssued": f"{issued:.0f}",
            "pfLate": f"{late:.0f}",
            "pfUseful": f"{useful:.0f}",
            "pfUnused": f"{stats[PREFETCHER + 'pfUnused']:.0f}",
            "demandMshrHitsAtPf": f"{hits:.0f}",
            "demandMshrHitsAtPfAlloc": f"{hits_alloc:.0f}",
            "coverage": f"{coverage:.9f}",
            "timeliness": f"{timeliness:.9f}",
            "speedup_over_nopf": f"{speedup:.9f}",
        }
        rows.append(row)
        if nopf_insts is not None and abs(sim_insts - nopf_insts) > 10:
            failures.append(
                f"{task}/{config}: simInsts differs from noPF "
                f"({sim_insts:g} vs {nopf_insts:g})"
            )
        if late > issued:
            failures.append(
                f"{task}/{config}: pfLate ({late:g}) exceeds pfIssued ({issued:g})"
            )
    return rows, failures


def collect(
    root: Path,
    task_names: list[str],
) -> tuple[Path, list[str]]:
    analysis = root / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    failures: list[str] = []
    for task in task_names:
        task_rows, task_failures = task_metrics(
            root,
            task,
        )
        rows.extend(task_rows)
        failures.extend(task_failures)

    output = analysis / "mechanism.csv"
    if rows:
        with output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    summary_rows: list[dict[str, str]] = []
    applications = sorted({str(row["application"]) for row in rows})
    for application in applications + ["overall"]:
        selected = (
            rows
            if application == "overall"
            else [row for row in rows if row["application"] == application]
        )
        for label in VARIANTS:
            variant_rows = [row for row in selected if row["variant"] == label]
            if not variant_rows:
                continue
            summary_rows.append(
                {
                    "application": application,
                    "variant": label,
                    "datasets": str(len(variant_rows)),
                    "coverage": (
                        f"{mean([float(row['coverage']) for row in variant_rows]):.9f}"
                    ),
                    "timeliness": (
                        f"{mean([float(row['timeliness']) for row in variant_rows]):.9f}"
                    ),
                    "speedup_over_nopf": (
                        f"{geomean([float(row['speedup_over_nopf']) for row in variant_rows]):.9f}"
                    ),
                }
            )
    summary = analysis / "mechanism_summary.csv"
    if summary_rows:
        with summary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summary_rows[0]))
            writer.writeheader()
            writer.writerows(summary_rows)

    report = analysis / "mechanism_validation.txt"
    report.write_text(
        (
            "MECHANISM VALIDATION FAILED\n- " + "\n- ".join(failures) + "\n"
            if failures
            else f"MECHANISM VALIDATION PASSED: {len(task_names)} task(s)\n"
        ),
        encoding="utf-8",
    )
    return output, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--tasks", nargs="+", required=True)
    args = parser.parse_args()
    output, failures = collect(
        args.output_root.resolve(),
        args.tasks,
    )
    print(f"mechanism results: {output}")
    if failures:
        print("MECHANISM VALIDATION FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"MECHANISM VALIDATION PASSED: {len(args.tasks)} task(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
