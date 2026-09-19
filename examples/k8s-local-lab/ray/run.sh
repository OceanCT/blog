#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
export PATH="$root/runtime/bin:$PATH"
export DOCKER_CONTEXT=colima-learning-lab
unset DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH
mkdir -p "$root/results"
docker build -t learning-lab-ray:2.58.0 "$root/ray"
docker run --rm --init --cpus=2 --memory=2g --shm-size=256m learning-lab-ray:2.58.0 2>&1 | tee "$root/results/ray.log"
