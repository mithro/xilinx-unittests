# SPDX-License-Identifier: Apache-2.0
# xut-sim: the one simulator container of spec §16 step 2 (spec rev 3.1).
# Bump SIM_IMAGE in tools/xut/container.py whenever this file changes.
# iverilog is pinned to the live trixie mirror's 12.0-2+b1. If it ever leaves the mirror,
# point both stages' apt sources at snapshot.debian.org for the base digest's date and
# record the snapshot timestamp here.
ARG BASE=debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a

# ---- stage 1: Verilator from the upstream tag (cocotb 2.0.1 needs >= 5.036) ----
FROM ${BASE} AS verilator
ARG VERILATOR_TAG=v5.048
ARG VERILATOR_SHA=d0aa828c217410fffc73d92077b6f4f54830357c
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git ca-certificates autoconf g++ make flex bison help2man perl python3 \
      libfl2 libfl-dev zlib1g zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "$VERILATOR_TAG" https://github.com/verilator/verilator /src/verilator \
 && cd /src/verilator \
 && test "$(git rev-parse HEAD)" = "$VERILATOR_SHA" \
 && autoconf \
 && ./configure --prefix=/opt/verilator \
 && make -j"$(nproc)" \
 && make install \
 && rm -rf /src/verilator

# ---- stage 2: the runtime image ----
FROM ${BASE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      iverilog=12.0-2+b1 \
      g++ make perl \
      python3 python3-venv libpython3.13 \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=verilator /opt/verilator /opt/verilator
COPY requirements-cocotb.txt /opt/requirements-cocotb.txt
RUN python3 -m venv /opt/cocotb \
 && /opt/cocotb/bin/pip install --no-cache-dir --require-hashes -r /opt/requirements-cocotb.txt
ENV PATH=/opt/verilator/bin:/opt/cocotb/bin:$PATH \
    VERILATOR_ROOT=/opt/verilator/share/verilator \
    PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.source=https://github.com/mithro/xilinx-unittests \
      org.opencontainers.image.licenses=Apache-2.0 \
      org.xut.verilator.tag=v5.048 \
      org.xut.verilator.commit=d0aa828c217410fffc73d92077b6f4f54830357c
