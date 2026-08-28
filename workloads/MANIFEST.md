# Workload Manifest

All executables are statically linked AArch64 ELF binaries for GNU/Linux
3.7.0 or later. The exact file hashes are in `workloads/SHA256SUMS`.

## Binaries

- `graph_aarch64_bfs_queue`: 613,088 bytes; Build ID
  `ef3fbf2d9afdf3bbcee7831d34c890e668de9e8e`.
- `graph_aarch64_mst_queue`: 608,968 bytes; Build ID
  `89e3432becdd162fca88207a7936fffbfaae23eb`.
- `graph_aarch64_sssp_queue`: 608,968 bytes; Build ID
  `4254e6e41bce9dcd1553b3dec60cb8d02c58213f`.
- `mchashjoins`: 708,272 bytes; Build ID
  `a5a980b86ce0cb9ecfc92211c103579e56a088fa`.

## Datasets

- `cage10.edge`: 4,383,042 bytes and 150,645 edge records.
- `sx-superuser.edge`: 14,791,726 bytes and 924,886 edge records.

## Task mapping

The authoritative command lines are in `tasks/tasks.conf`. The graph binaries
consume an edge-list path, node count, and graph-direction flag. Hash join
and group-by generate deterministic relations from the sizes and fixed
default seeds.

See `THIRD_PARTY.md` for provenance, licenses, modifications, and citations.
