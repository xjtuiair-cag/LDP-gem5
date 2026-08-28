# MICRO 2026 Artifact Evaluation Guide

The permanent archive is available through
<https://doi.org/10.5281/zenodo.21502244>.

## 1. What the artifact evaluates

This artifact provides a compact reproduction of the performance trend in
Fig. 18 of the paper *Loop-Decoupled Prefetcher for Linked Data Structure* and
a mechanism-level loop-decoupling ablation corresponding to Fig. 24.

The nine tasks cover:

- BFS, MST, and SSSP with the `cage10` and `sx-superuser` graph inputs;
- hash join probe with 1.28M build and probe tuples;
- group-by with 1.28M input tuples; and
- IPv4 lookup with 100,000 entries.

Each restored simulation uses the `O3_ARM_Neoverse_v2` CPU profile and
DDR5-6400 memory. The `fast` profile uses 10-million-instruction windows,
except that GB uses 60 million instructions to include its relevant later
phase. The `full` profile runs every workload to normal completion.

The compact artifact does not evaluate the other prefetchers or the full
13-application suite used in the paper. It is intended to reproduce the
no-prefetch versus LDP trend and directly test the paper's loop-decoupling
mechanism.

## 2. Components

- `src/mem/cache/prefetch/ldp.{cc,hh}`: LDP implementation.
- `configs/ldp/se.py`: ARM syscall-emulation configuration.
- `tasks/tasks.conf`: fixed task definitions.
- `workloads/`: AArch64 binaries and graph inputs.
- `scripts/reproduce.py`: one-command run, analysis, plot, and validation.
- `scripts/run.py`: lower-level checkpoint and simulation runner.
- `scripts/validate*.py`: comparison with profile-specific references.
- `expected/`: read-only reference data for the archived profiles.
- `checkpoints/`: supplied in the Docker image and archive runtime bundle.

Generated files are never written under `expected/`. Native and Docker runs
place all outputs under `results/<profile>/`.

## 3. Resource requirements

No special CPU, GPU, FPGA, kernel module, performance counter, or proprietary
software is required. The host executes an ARM target through gem5, so the
recommended host is x86-64 Linux with Docker Engine.

Four CPU cores are sufficient; additional cores increase simulation
parallelism. In local validation with 12 workers, the three-configuration
`fast` and `full` profiles completed in approximately 11 and 28 minutes,
respectively. Runtime varies with host CPU and the selected `--jobs` value.

## 4. Docker workflow

Pull the evaluated image:

```bash
docker pull ghcr.io/xjtuiair-cag/ldp-gem5:micro26-final
```

Create a host output directory and run the complete bounded workflow:

```bash
mkdir -p results
docker run --rm \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/results:/results" \
  ghcr.io/xjtuiair-cag/ldp-gem5:micro26-final
```

This single command runs no-prefetching, LDP without loop decoupling, and full
LDP for all nine tasks. It then:

1. reports task, application, and overall LDP speedups;
2. validates the speedup reproduction;
3. validates the loop-decoupling ablation; and
4. generates `results/fast/analysis/mechanism.png`.

The final success messages include:

```text
VALIDATION PASSED: 9 task(s)
MECHANISM REPRODUCTION PASSED
```

The runner only prints the Fig. 18 consistency statement after both
validations pass. The PNG is written through the bind mount and can be opened
directly on the host; no graphical environment is needed in the container.

Run the completion-based profile in a separate profile directory:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/results:/results" \
  ghcr.io/xjtuiair-cag/ldp-gem5:micro26-final \
  --run-profile full --jobs 4
```

### Bind-mount permissions

The container process must be able to create files in the host-mounted output
directory. The documented
`--user "$(id -u):$(id -g)" -e HOME=/tmp` options map it to the invoking POSIX
user, preventing the UID/GID mismatch that can otherwise make `/results`
unwritable or leave root/container-owned files on the host.

If a POSIX host still reports a permission error, verify that the current user
owns `results`; as a temporary fallback, use `chmod a+rwx results`. On Windows
Docker Desktop, `id` is not available in PowerShell: place `results` in a
writable shared local directory and omit `--user`; WSL users can use the
documented POSIX command from a Linux-filesystem directory.

## 5. Native workflow

Install dependencies and build gem5:

```bash
sudo apt-get update
sudo apt-get install -y build-essential scons python3.10-dev python3-pil \
  fonts-dejavu-core zlib1g-dev m4 pkg-config
source sourceme
PYTHON_CONFIG=python3.10-config \
CCFLAGS_EXTRA='-include stdint.h' \
scons build/ARM_LDP/gem5.opt -j"$(nproc)"
```

Without packaged checkpoints, the runner first executes the workload's
built-in checkpoint phase and stores the resulting checkpoint under
`results/fast/<task>/`. Run the complete workflow with:

```bash
python3 scripts/reproduce.py --run-profile fast --jobs 4
```

With the archive checkpoint bundle:

```bash
python3 scripts/reproduce.py \
  --checkpoint-root /path/to/checkpoints \
  --run-profile fast --jobs 4
```

The native workflow presents evaluation as two result substeps:

1. **Overall speedup:** `speedup.csv` and `summary.txt` compare full LDP with
   no-prefetching and report task, application, and overall speedups.
2. **Loop-decoupling ablation:** `mechanism.csv`,
   `mechanism_summary.csv`, and `mechanism.png` compare full LDP with the same
   prefetcher after disabling only loop decoupling.

Both substeps are generated and validated by `scripts/reproduce.py`; no
separate analysis command is required.

## 6. Outputs and interpretation

Each task directory records the actual gem5 commands, simulator logs, and
statistics for:

- `nopf_restored`: no-prefetch baseline;
- `ldp_no_loop_restored`: LDP without loop decoupling; and
- `ldp_restored`: full LDP.

The analysis directory contains:

- `speedup.csv` and `summary.txt`: overall performance reproduction;
- `mechanism.csv` and `mechanism_summary.csv`: auditable ablation data;
- `mechanism_validation.txt`: collection checks; and
- `mechanism.png`: Fig. 24-style visualization.

The `fast` profile is intended for timely functional and trend validation.
Running to completion gives LDP more opportunities to act in later workload
phases: the `full` profile therefore shows a substantially stronger aggregate
benefit and more closely follows the full-execution trend in the paper. Fast
and full results are kept separate and must not be combined into one mean.

## 7. IPv4 note

Under the AE configuration, IPv4 without loop decoupling identifies only the
outermost streaming access. Those few requests are almost always timely, so
the reported timeliness is close to 100%; however, the prefetcher issues very
few requests, coverage is nearly zero, and the configuration provides almost
no speedup. Enabling loop decoupling exposes the complete dependent access
relation, allowing LDP to issue the useful linked-data-structure prefetches
while retaining high timeliness and achieving a clear speedup.

This illustrates why timeliness alone does not imply effectiveness when the
mechanism covers almost none of the target accesses.

## 8. Customization and troubleshooting

`scripts/reproduce.py --help` lists the supported profile, checkpoint,
parallelism, and task controls. `scripts/run.py --help` exposes lower-level
collection and CPU-profile options. Results from custom instruction limits or
CPU profiles are exploratory and should not be compared with the archived
references.

- `gem5 binary not found`: use the Docker image or complete the native build.
- `Missing checkpoint(s)`: verify one `cpt.*` directory containing `m5.cpt`
  under each selected task.
- `VALIDATION FAILED`: inspect the named task's stats and simulator log.
- Docker permission errors: retain the UID/GID mapping and verify that the
  bind-mounted host directory is writable.

Report evaluation problems through the
[GitHub issue tracker](https://github.com/xjtuiair-cag/LDP-gem5/issues) and
include the image digest, host OS, command, and failing task log.
