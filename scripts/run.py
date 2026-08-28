#!/usr/bin/env python3
"""Run selected LDP-gem5 workloads in parallel and collect speedups."""

from __future__ import annotations

import argparse
import csv
import math
import os
import shlex
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from mechanism import collect as collect_mechanism
from plot_mechanism import load as load_mechanism_summary
from plot_mechanism import render as render_mechanism_figure


ROOT = Path(__file__).resolve().parents[1]
CPU_TYPE = "O3_ARM_Neoverse_v2"
BASE_CPU_TYPE = "AtomicSimpleCPU"
FAST_MAX_INSTS = 10_000_000
FAST_MAX_INSTS_BY_TASK = {
    "database_gb_m": 60_000_000,
}
CPU_PROFILES = {
    "O3_ARM_Neoverse_v2": {
        "mem_channels": "4",
        "tlb_size": None,
        "cache_args": [],
    },
    "O3_ARM_Neoverse": {
        "mem_channels": "2",
        "tlb_size": None,
        "cache_args": [
            "--l1i_size",
            "32kB",
            "--l1d_size",
            "48kB",
            "--l1i_assoc",
            "8",
            "--l1d_assoc",
            "12",
            "--l1d_mshr_num",
            "8",
            "--l2_size",
            "512kB",
            "--l2_mshr_num",
            "32",
        ],
    },
}
DEFAULT_TASKS = ROOT / "tasks" / "tasks.conf"
DEFAULT_GEM5 = ROOT / "build" / "ARM_LDP" / "gem5.opt"
DEFAULT_RESULTS_ROOT = ROOT / "results"
CONFIG = ROOT / "configs" / "ldp" / "se.py"
LDP_CONFIG_ARGS = {
    "ldp_restored": [],
    "ldp_no_loop_restored": [
        "--ldp-offsetfilter-enable",
        "false",
    ],
}
def load_tasks(path: Path) -> dict[str, list[str]]:
    tasks: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = shlex.split(line)
        if len(fields) < 2:
            raise ValueError(f"Invalid task line: {line}")
        tasks[fields[0]] = fields[1:]
    return tasks


def checkpoint_exists(task_dir: Path) -> bool:
    return any(
        checkpoint.is_dir() and (checkpoint / "m5.cpt").exists()
        for checkpoint in task_dir.glob("cpt.*")
    )


def run_one(
    task_name: str,
    command: list[str],
    gem5: Path,
    output_root: Path,
    checkpoint_root: Path,
    cpu_type: str,
    config_name: str,
    skip_existing: bool,
    max_insts: int | None,
) -> tuple[str, str, int]:
    task_dir = output_root / task_name
    checkpoint_dir = checkpoint_root / task_name
    outdir = checkpoint_dir if config_name == "base" else task_dir / config_name
    stats_file = task_dir / (
        "stats.txt" if config_name == "base" else f"stats_{config_name}.txt"
    )
    stats = stats_file
    if skip_existing and stats.exists() and (
        config_name != "base" or checkpoint_exists(task_dir)
    ):
        return task_name, config_name, 0
    task_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    options = command[1:]
    executable = command[0]
    profile = CPU_PROFILES[cpu_type]
    run_cpu_type = BASE_CPU_TYPE if config_name == "base" else cpu_type
    gem5_cmd = [
        str(gem5),
        "-d",
        str(outdir),
        "--stats-file",
        str(stats_file),
        str(CONFIG),
        "--cmd",
        str((ROOT / executable).resolve()),
        "--options",
        " ".join(shlex.quote(x) for x in options),
        "--cpu-type",
        run_cpu_type,
        "--cpu-clock",
        "4GHz",
        "--sys-clock",
        "1GHz",
        "--num-cpus",
        "1",
        "--mem-type",
        "DDR5_6400_4x8",
        "--mem-channels",
        profile["mem_channels"],
        "--caches",
        "--l2cache",
        "--l3cache",
    ]
    if profile["tlb_size"] is not None:
        gem5_cmd += ["--tlb-size", profile["tlb_size"]]
    gem5_cmd += profile["cache_args"]
    if config_name != "base" and max_insts is not None:
        gem5_cmd += ["--maxinsts", str(max_insts)]
    if config_name in LDP_CONFIG_ARGS:
        gem5_cmd += [
            "--l1d-hwp-type",
            "LDPPrefetcher",
            "--ldp-notify",
            "l1",
        ]
        gem5_cmd += LDP_CONFIG_ARGS[config_name]
    if config_name == "base":
        gem5_cmd += [
            "--checkpoint-dir",
            str(checkpoint_dir),
            "--max-checkpoints",
            "1",
        ]
    else:
        gem5_cmd += [
            "--checkpoint-dir",
            str(checkpoint_dir),
            "--checkpoint-restore",
            "1",
            "--restore-with-cpu",
            cpu_type,
        ]
    (outdir / "command.txt").write_text(
        " ".join(shlex.quote(x) for x in gem5_cmd) + "\n", encoding="utf-8"
    )
    log_file = task_dir / f"{task_name}_{config_name}.log"
    with log_file.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            gem5_cmd,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return task_name, config_name, result.returncode


def run_phase(pool, jobs, phase: str):
    """Run one phase and emit compact progress updates every two minutes."""
    futures = {pool.submit(run_one, *job) for job in jobs}
    pending = set(futures)
    total = len(pending)
    completed = 0
    started = time.monotonic()
    while pending:
        done, pending = wait(
            pending, timeout=120, return_when=FIRST_COMPLETED
        )
        if not done:
            elapsed = int(time.monotonic() - started)
            print(
                f"[{phase}] progress {completed:02d}/{total:02d} complete; "
                f"{len(pending):02d} running; elapsed {elapsed // 60:02d}m",
                flush=True,
            )
            continue
        for future in done:
            task, config, code = future.result()
            completed += 1
            state = "OK" if code == 0 else f"FAILED({code})"
            print(
                f"[{phase}] {completed:02d}/{total:02d} "
                f"{task}/{config}: {state}",
                flush=True,
            )
            yield task, config, code


def read_sim_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "simSeconds":
            try:
                return float(fields[1])
            except ValueError:
                return None
    return None


def application_name(task: str) -> str:
    """Return the application name shared by its input-dataset variants."""
    if task.startswith("graph_"):
        for suffix in ("_cg10", "_ss"):
            if task.endswith(suffix):
                return task[: -len(suffix)]
    return task


def geomean(values: list[float]) -> float | None:
    positive = [value for value in values if value > 0]
    return math.prod(positive) ** (1 / len(positive)) if positive else None


def collect(root: Path, task_names: list[str]) -> Path:
    analysis = root / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in task_names:
        nopf_path = root / task / "stats_nopf_restored.txt"
        ldp_path = root / task / "stats_ldp_restored.txt"
        # Keep collection usable for outputs generated by the previous runner.
        if not nopf_path.exists():
            nopf_path = root / task / "nopf_restored" / "stats.txt"
        if not ldp_path.exists():
            ldp_path = root / task / "ldp_restored" / "stats.txt"
        nopf = read_sim_seconds(nopf_path)
        ldp = read_sim_seconds(ldp_path)
        speedup = nopf / ldp if nopf and ldp and ldp > 0 else None
        rows.append(
            {
                "task": task,
                "nopf_restored_simSeconds": nopf or "",
                "ldp_restored_simSeconds": ldp or "",
                "speedup_ldp_over_nopf": f"{speedup:.6f}" if speedup else "",
                "status": "ok" if speedup else "missing",
            }
        )
    output = analysis / "speedup.csv"
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    valid = [
        float(row["speedup_ldp_over_nopf"])
        for row in rows
        if row["speedup_ldp_over_nopf"]
    ]
    grouped: dict[str, list[float]] = {}
    for row in rows:
        value = row["speedup_ldp_over_nopf"]
        if value:
            grouped.setdefault(application_name(row["task"]), []).append(float(value))

    summary_lines = [f"tasks={len(valid)}/{len(rows)}"]
    print("[ANALYSIS] application speedups (LDP over no-prefetch):", flush=True)
    for application, values in grouped.items():
        value = geomean(values)
        if value is None:
            continue
        dataset_note = f" ({len(values)} datasets)" if len(values) > 1 else ""
        summary_lines.append(
            f"application={application} datasets={len(values)} "
            f"geomean_speedup={value:.6f}"
        )
        print(f"[ANALYSIS] {application}{dataset_note}: {value:.6f}x", flush=True)

    overall = geomean(valid)
    if overall is not None:
        summary_lines.append(f"overall_geomean_speedup={overall:.6f}")
        print(f"[ANALYSIS] overall geomean: {overall:.6f}x", flush=True)
    else:
        summary_lines.append("overall_geomean_speedup=missing")
        print("[ANALYSIS] overall geomean: missing data", flush=True)
    (analysis / "summary.txt").write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-file", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--tasks", nargs="+", help="Task names; default is all tasks")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--gem5", type=Path, default=DEFAULT_GEM5)
    parser.add_argument(
        "--outdir",
        type=Path,
        help="Output root; defaults to results/<run-profile>",
    )
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        help=(
            "Read checkpoints from this root and write results under --outdir. "
            "When omitted, checkpoints are generated under --outdir."
        ),
    )
    parser.add_argument(
        "--max-insts",
        type=int,
        help="Override the selected run profile with one instruction limit",
    )
    parser.add_argument(
        "--run-profile",
        choices=("fast", "full"),
        default="fast",
        help=(
            "fast: 10M instructions per task except GB at 60M; "
            "full: run every restored task to normal completion"
        ),
    )
    parser.add_argument(
        "--cpu-type",
        choices=tuple(CPU_PROFILES),
        default=CPU_TYPE,
        help="CPU profile; default matches the LDP configuration",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument(
        "--mechanism-ablation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Run LDP with loop decoupling disabled and collect mechanism "
            "metrics (enabled by default)"
        ),
    )
    args = parser.parse_args()

    task_map = load_tasks(args.task_file.resolve())
    selected = args.tasks or list(task_map)
    unknown = sorted(set(selected) - task_map.keys())
    if unknown:
        parser.error(f"Unknown tasks: {', '.join(unknown)}")
    output_root = (
        args.outdir or DEFAULT_RESULTS_ROOT / args.run_profile
    ).resolve()
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / f".ldp-write-test-{os.getpid()}"
        probe.write_text("writable\n", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        parser.error(
            f"output directory is not writable: {output_root} ({error}). "
            "For Docker bind mounts, add "
            '--user "$(id -u):$(id -g)" -e HOME=/tmp.'
        )
    checkpoint_root = (
        args.checkpoint_root.resolve()
        if args.checkpoint_root
        else output_root
    )
    if args.max_insts is not None and args.max_insts <= 0:
        parser.error("--max-insts must be positive")
    if args.checkpoint_root:
        missing_checkpoints = [
            task
            for task in selected
            if not checkpoint_exists(checkpoint_root / task)
        ]
        if missing_checkpoints:
            parser.error(
                "Missing checkpoint(s) under --checkpoint-root: "
                + ", ".join(missing_checkpoints)
            )
    if not args.collect_only:
        if not args.gem5.exists():
            parser.error(f"gem5 binary not found: {args.gem5}")
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            pending = {}
            completed = 0
            started = time.monotonic()

            def submit_restore(task: str) -> None:
                configs = ["nopf_restored", "ldp_restored"]
                if args.mechanism_ablation:
                    configs.append("ldp_no_loop_restored")
                if args.max_insts is not None:
                    restore_max_insts = args.max_insts
                elif args.run_profile == "full":
                    restore_max_insts = None
                else:
                    restore_max_insts = FAST_MAX_INSTS_BY_TASK.get(
                        task, FAST_MAX_INSTS
                    )
                for config in configs:
                    future = pool.submit(
                        run_one,
                        task,
                        task_map[task],
                        args.gem5.resolve(),
                        output_root,
                        checkpoint_root,
                        args.cpu_type,
                        config,
                        args.skip_existing,
                        restore_max_insts,
                    )
                    pending[future] = ("restore", task, config)
                submitted = " + ".join(f"{task}/{config}" for config in configs)
                print(
                    f"[RESTORE] submitted {submitted}",
                    flush=True,
                )

            base_count = 0
            reused_count = 0
            for task in selected:
                if checkpoint_exists(checkpoint_root / task):
                    reused_count += 1
                    submit_restore(task)
                    continue
                future = pool.submit(
                    run_one,
                    task,
                    task_map[task],
                    args.gem5.resolve(),
                    output_root,
                    checkpoint_root,
                    args.cpu_type,
                    "base",
                    False,
                    args.max_insts or FAST_MAX_INSTS,
                )
                pending[future] = ("base", task, "base")
                base_count += 1

            print(
                f"[BASE] submitted {base_count:02d} task(s); "
                f"reusing {reused_count:02d} existing checkpoint(s); "
                "restore jobs submit immediately after checkpoint detection",
                flush=True,
            )
            print(
                "[RUN] progress interval 120s",
                flush=True,
            )
            failed = 0
            while pending:
                done, _ = wait(
                    set(pending), timeout=120, return_when=FIRST_COMPLETED
                )
                if not done:
                    elapsed = int(time.monotonic() - started)
                    print(
                        f"[RUN] progress {completed:02d} completed; "
                        f"{len(pending):02d} running/queued; "
                        f"elapsed {elapsed // 60:02d}m",
                        flush=True,
                    )
                    continue
                for future in done:
                    kind, task, config = pending.pop(future)
                    try:
                        result_task, result_config, code = future.result()
                    except Exception as error:
                        code = -1
                        failed += 1
                        print(
                            f"[{kind.upper()}] {task}/{config}: "
                            f"FAILED({error})",
                            flush=True,
                        )
                    else:
                        if result_task != task or result_config != config:
                            print(
                                f"[RUN] unexpected result for {task}/{config}: "
                                f"{result_task}/{result_config}",
                                flush=True,
                            )
                    completed += 1
                    if code == 0:
                        print(
                            f"[{kind.upper()}] {completed:02d} "
                            f"{task}/{config}: OK",
                            flush=True,
                        )
                    elif code != -1:
                        failed += 1
                        print(
                            f"[{kind.upper()}] {completed:02d} "
                            f"{task}/{config}: FAILED({code})",
                            flush=True,
                        )
                    if (
                        kind == "base"
                        and code == 0
                        and checkpoint_exists(checkpoint_root / task)
                    ):
                        print(
                            f"[BASE] {task} checkpoint ready; "
                            "submitting restore jobs immediately",
                            flush=True,
                        )
                        submit_restore(task)
                    elif kind == "base" and code == 0:
                        failed += 1
                        print(
                            f"[BASE] {task} finished without a valid checkpoint; "
                            "restore jobs not submitted",
                            flush=True,
                        )
            if failed:
                print(f"[RUN] {failed} stage(s) failed", flush=True)
    result = collect(output_root, selected)
    print(f"speedup results: {result}")
    mechanism_failures: list[str] = []
    if args.mechanism_ablation:
        mechanism_result, mechanism_failures = collect_mechanism(
            output_root,
            selected,
        )
        print(f"mechanism results: {mechanism_result}")
        mechanism_summary = mechanism_result.parent / "mechanism_summary.csv"
        mechanism_figure = mechanism_result.parent / "mechanism.png"
        profile_label = (
            "Fast profile (GB: 60M; others: 10M)"
            if args.run_profile == "fast"
            else "Full profile (program completion)"
        )
        render_mechanism_figure(
            load_mechanism_summary(mechanism_summary),
            mechanism_figure,
            profile_label,
        )
        print(f"mechanism figure: {mechanism_figure}")
    missing = [
        task
        for task in selected
        if read_sim_seconds(output_root / task / "stats_nopf_restored.txt")
        is None
        or read_sim_seconds(output_root / task / "stats_ldp_restored.txt")
        is None
    ]
    if missing:
        print(
            "[ANALYSIS] missing valid paired results: " + ", ".join(missing),
            flush=True,
        )
        return 1
    if not args.collect_only and failed:
        return 1
    if mechanism_failures:
        print(
            "[ANALYSIS] invalid mechanism results: "
            + "; ".join(mechanism_failures),
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
