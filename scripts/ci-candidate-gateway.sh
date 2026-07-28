#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 <candidate-wheel> <expected-sha256>" >&2
  exit 2
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
candidate_wheel="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
expected_sha256="$2"
export UV_CACHE_DIR="${GIGALOOM_UV_CACHE_DIR:-${repository_root}/.cache/uv}"

if [[ ! -f "${candidate_wheel}" || "${candidate_wheel}" != *.whl ]]; then
  echo "candidate must be an existing wheel" >&2
  exit 1
fi
if [[ ! "${expected_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "expected SHA-256 must contain 64 lowercase hexadecimal characters" >&2
  exit 1
fi

actual_sha256="$(
  python3 -c \
    'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
    "${candidate_wheel}"
)"
if [[ "${actual_sha256}" != "${expected_sha256}" ]]; then
  echo "candidate gateway digest changed" >&2
  exit 1
fi

if [[ -e "${repository_root}/uv.lock" ]]; then
  echo "uv.lock is deferred until repository-split gate S5-03B" >&2
  exit 1
fi

scratch="$(mktemp -d "${TMPDIR:-/tmp}/gigaloom-candidate.XXXXXXXX")"
trap 'rm -rf "${scratch}"' EXIT

cd "${repository_root}"
uv venv --no-project --python "${GIGALOOM_PYTHON:-3.13}" "${scratch}/venv"
"${scratch}/venv/bin/python" \
  packages/gpt2giga-harness/asset_contract.py \
  --require-clean
uv build \
  --package gpt2giga-harness \
  --wheel \
  --no-sources \
  --out-dir "${scratch}/dist"
harness_wheel="$(find "${scratch}/dist" -maxdepth 1 -name 'gpt2giga_harness-*.whl' -print -quit)"
if [[ -z "${harness_wheel}" ]]; then
  echo "standalone GigaLoom wheel was not produced" >&2
  exit 1
fi

uv pip install \
  --python "${scratch}/venv/bin/python" \
  --no-sources \
  "${candidate_wheel}" \
  "${harness_wheel}[gpt2giga]"

EXPECTED_GATEWAY_VERSION=0.2.6a1 \
  "${scratch}/venv/bin/python" -I -c '
import importlib.metadata
import os

from gpt2giga_harness.gpt2giga_preset import require_gpt2giga_preset

assert importlib.metadata.version("gpt2giga") == os.environ["EXPECTED_GATEWAY_VERSION"]
runtime = require_gpt2giga_preset()
assert runtime.client_type.__module__.split(".", 1)[0] == "gigachat"
assert runtime.load_config.__module__ == "gpt2giga.cli"
'

if [[ -e "${repository_root}/uv.lock" ]]; then
  echo "candidate smoke persisted a forbidden uv.lock" >&2
  exit 1
fi
