#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment="${GIGALOOM_VENV:-${repository_root}/.venv}"
python="${environment}/bin/python"
export UV_CACHE_DIR="${GIGALOOM_UV_CACHE_DIR:-${repository_root}/.cache/uv}"

require_unlocked_workspace() {
  if [[ -e "${repository_root}/uv.lock" ]]; then
    echo "uv.lock is deferred until repository-split gate S5-03B" >&2
    exit 1
  fi
}

require_environment() {
  if [[ ! -x "${python}" ]]; then
    echo "run ./scripts/ci-base.sh sync first" >&2
    exit 1
  fi
}

command="${1:-}"
if [[ -z "${command}" ]]; then
  echo "usage: $0 {sync|ruff-check|ruff-format-check|pytest} [args...]" >&2
  exit 2
fi
shift

cd "${repository_root}"
require_unlocked_workspace

case "${command}" in
  sync)
    uv venv \
      --clear \
      --no-project \
      --python "${GIGALOOM_PYTHON:-3.13}" \
      "${environment}"
    "${python}" packages/gpt2giga-harness/asset_contract.py --require-clean
    uv pip install \
      --python "${python}" \
      --no-sources \
      --group dev \
      --group integrations \
      --editable packages/gpt2giga-harness
    require_unlocked_workspace
    ;;
  ruff-check)
    require_environment
    if [[ "$#" -eq 0 ]]; then
      set -- .
    fi
    exec "${environment}/bin/ruff" check "$@"
    ;;
  ruff-format-check)
    require_environment
    if [[ "$#" -eq 0 ]]; then
      set -- .
    fi
    exec "${environment}/bin/ruff" format --check "$@"
    ;;
  pytest)
    require_environment
    exec "${python}" -m pytest "$@"
    ;;
  *)
    echo "unknown command: ${command}" >&2
    exit 2
    ;;
esac
