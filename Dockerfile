FROM ubuntu:22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
    libboost-all-dev \
    libgoogle-perftools-dev \
    libhdf5-dev \
    libpng-dev \
    libprotobuf-dev \
    m4 \
    pkg-config \
    protobuf-compiler \
    python3-dev \
    scons \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .
RUN PYTHON_CONFIG=python3-config \
    CCFLAGS_EXTRA="-include stdint.h" \
    scons build/ARM_LDP/gem5.opt -j"$(nproc)" --ignore-style

FROM ubuntu:22.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libcurl4 \
    libgoogle-perftools4 \
    libhdf5-103-1 \
    libhdf5-cpp-103-1 \
    libpng16-16 \
    libprotobuf23 \
    libpython3.10 \
    python3 \
    python3-pil \
    fonts-dejavu-core \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash ldp
WORKDIR /opt/ldp

COPY --from=builder /src/build/ARM_LDP/gem5.opt /opt/ldp/bin/gem5.opt
COPY configs /opt/ldp/configs
COPY expected /opt/ldp/expected
COPY scripts /opt/ldp/scripts
COPY tasks /opt/ldp/tasks
COPY workloads /opt/ldp/workloads
COPY checkpoints /opt/ldp/checkpoints
COPY ARTIFACT.md LICENSE COPYING THIRD_PARTY.md /opt/ldp/

RUN chmod -R a-w /opt/ldp/checkpoints /opt/ldp/expected \
    && mkdir /results \
    && chown ldp:ldp /results

ENV PYTHONUNBUFFERED=1
USER ldp

LABEL org.opencontainers.image.title="LDP-gem5 MICRO 2026 Artifact" \
      org.opencontainers.image.source="https://github.com/xjtuiair-cag/LDP-gem5" \
      org.opencontainers.image.licenses="BSD-3-Clause" \
      org.opencontainers.image.version="micro26-final"

ENTRYPOINT ["python3", "scripts/reproduce.py"]
CMD ["--run-profile", "fast", "--jobs", "4"]
