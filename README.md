# LDP-gem5

This repository contains the MICRO 2026 artifact for the Loop-Decoupled
Prefetcher (LDP). It provides a compact ARM syscall-emulation gem5, the LDP
implementation, fixed AArch64 workloads and inputs, and an automated
reproduction workflow.

LDP targets linked-data-structure traversals whose inner pointer-chasing
accesses are interleaved with outer-loop accesses. It uses loop decoupling,
bidirectional pattern reconstruction, and cross-loop prefetching to recognize
these accesses and start future traversals early.

## Artifact scope

The artifact evaluates six applications (BFS, MST, SSSP, hash join probe,
group-by, and IPv4 lookup) in nine task/input combinations. The workflow
compares no-prefetching, LDP without loop decoupling, and full LDP. It
reproduces the performance direction and trend of the representative subset
from Fig. 18 and generates a Fig. 24-style loop-decoupling ablation plot.

This compact workflow does not reproduce all 13 paper applications or all
prefetchers in Fig. 18. The `fast` profile uses bounded simulation windows for
timely evaluation; the `full` profile runs every task to normal completion and
more closely reflects the paper's full-execution trend.

## One-command Docker reproduction

The image includes the simulator and compatible checkpoints. The bind mount
keeps all generated files in a separate host-side `results` directory:

```bash
mkdir -p results
docker run --rm \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/results:/results" \
  ghcr.io/xjtuiair-cag/ldp-gem5:micro26-final
```

The default command runs and validates the `fast` profile, prints task,
application, and overall speedups, and creates:

```text
results/fast/analysis/speedup.csv
results/fast/analysis/summary.txt
results/fast/analysis/mechanism.csv
results/fast/analysis/mechanism_summary.csv
results/fast/analysis/mechanism.png
```

Open `results/fast/analysis/mechanism.png` directly on the host to view the
Fig. 24-style result. No GUI or display server is required inside Docker.

Run the completion-based profile with:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/results:/results" \
  ghcr.io/xjtuiair-cag/ldp-gem5:micro26-final \
  --run-profile full --jobs 4
```

The UID/GID mapping makes bind-mounted files host-owned and writable. On
Windows Docker Desktop, use a writable shared local directory; see
[ARTIFACT.md](ARTIFACT.md) for platform-specific guidance.

## Native build and reproduction

The tested native environment is Ubuntu 24.04 x86-64 with Python 3.10:

```bash
sudo apt-get update
sudo apt-get install -y build-essential scons python3.10-dev python3-pil \
  fonts-dejavu-core zlib1g-dev m4 pkg-config
source sourceme
PYTHON_CONFIG=python3.10-config \
CCFLAGS_EXTRA='-include stdint.h' \
scons build/ARM_LDP/gem5.opt -j"$(nproc)"
```

Run the complete workflow:

```bash
python3 scripts/reproduce.py --run-profile fast --jobs 4
```

If using separately downloaded checkpoints:

```bash
python3 scripts/reproduce.py \
  --checkpoint-root /path/to/checkpoints \
  --run-profile fast --jobs 4
```

All generated checkpoints, simulator outputs, reports, and figures remain
under `results/`; the profile-specific reference values under `expected/` are
read-only validation inputs.

For selected-task or collection-only experiments, use `scripts/run.py --help`.
The exact evaluation procedure and limitations are documented in
[ARTIFACT.md](ARTIFACT.md).

## License and contact

The source code is distributed under the BSD 3-Clause license. Workload and
dataset provenance and licenses are documented in
[THIRD_PARTY.md](THIRD_PARTY.md).

Contact: Zong Pengchen, Xi'an Jiaotong University,
[zongpc.me@outlook.com](mailto:zongpc.me@outlook.com).
