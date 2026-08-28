# Third-Party Software, Workloads, and Data

The repository-level BSD 3-Clause license applies to the LDP-gem5 changes
authored for this artifact. It does not replace licenses or copyright notices
of upstream gem5, bundled libraries, workload code, or datasets.

## gem5

LDP-gem5 is derived from gem5 22.1.0.0:

- Source: <https://github.com/gem5/gem5>
- License: BSD-style licenses; see `LICENSE`, `COPYING`, individual source
  headers, and license files under `ext/`.

## AArch64 workload binaries

The binaries under `workloads/bin/` are statically linked AArch64 executables
built with gem5 pseudo-instructions for checkpointing and exit. They are
provided to make the evaluated instruction stream immutable.

### Graph workloads

`graph_aarch64_bfs_queue`, `graph_aarch64_mst_queue`, and
`graph_aarch64_sssp_queue` are author-created benchmark drivers using the
Boost Graph Library. The benchmark-driver copyright is held by the artifact
authors and is released for this artifact under BSD 3-Clause. Boost components
are under the Boost Software License 1.0:
<https://www.boost.org/users/license.html>.

### Hash join and group-by workload

`mchashjoins` is based on the ETH Zurich Systems Group main-memory hash-join
implementation:

- Upstream: <https://github.com/mars-research/vldb13-eth-hashjoin>
- Copyright: 2012–2013 ETH Zurich, Systems Group
- Citation: Cagri Balkesen, Jens Teubner, Gustavo Alonso, and M. Tamer Özsu,
  “Main-Memory Hash Joins on Multi-Core CPUs: Tuning to the Underlying
  Hardware,” ICDE 2013.

The artifact binary contains author modifications for AArch64 gem5
checkpointing and the group-by experiment. Redistribution permission for the
evaluated binary is held by the artifact authors. The upstream project does
not publish a repository-wide SPDX license; therefore, this notice does not
grant rights to reuse the ETH Zurich implementation outside this research
artifact. The corresponding source and permission record must accompany the
final Zenodo deposit.

## Graph datasets

The graph files are redistributed under Creative Commons Attribution 4.0
(CC BY 4.0), following the SuiteSparse Matrix Collection data license:
<https://creativecommons.org/licenses/by/4.0/>.

### `cage10.edge`

- Source: SuiteSparse Matrix Collection, `vanHeukelum/cage10`
- Landing page: <https://sparse.tamu.edu/vanHeukelum/cage10>
- Artifact form: 150,645 weighted source/destination edges
- Transformation: Matrix coordinate entries were exported as whitespace
  separated `source destination weight` records for the graph driver.

Please cite the original matrix authors and:

Timothy A. Davis and Yifan Hu, “The University of Florida Sparse Matrix
Collection,” ACM Transactions on Mathematical Software, 38(1), 2011.

### `sx-superuser.edge`

- Source: SNAP Super User temporal network
- Landing page: <https://snap.stanford.edu/data/sx-superuser.html>
- Artifact form: 924,886 static weighted source/destination edges
- Transformation: the static graph was exported as whitespace separated
  `source destination weight` records; temporal timestamps are not used.

Please cite:

Ashwin Paranjape, Austin R. Benson, and Jure Leskovec, “Motifs in Temporal
Networks,” WSDM 2017.

## Integrity

`workloads/SHA256SUMS` records the exact binaries and datasets evaluated by
the artifact. Run:

```bash
sha256sum -c workloads/SHA256SUMS
```
