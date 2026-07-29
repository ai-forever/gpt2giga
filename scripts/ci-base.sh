#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
environment="${GIGALOOM_VENV:-${repository_root}/.venv}"
python="${environment}/bin/python"
export UV_CACHE_DIR="${GIGALOOM_UV_CACHE_DIR:-${repository_root}/.cache/uv}"
export UV_PROJECT_ENVIRONMENT="${environment}"

require_lock() {
  if [[ ! -f "${repository_root}/uv.lock" ]]; then
    echo "committed uv.lock is required" >&2
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
  echo "usage: $0 {sync|sync-all-extras|ruff-check|ruff-format-check|pytest} [args...]" >&2
  exit 2
fi
shift

cd "${repository_root}"
require_lock

case "${command}" in
  sync | sync-all-extras)
    sync_args=(
      --locked
      --all-groups
      --python "${GIGALOOM_PYTHON:-3.13}"
    )
    if [[ "${command}" == "sync-all-extras" ]]; then
      sync_args+=(--all-extras)
    fi
    uv sync "${sync_args[@]}"
    "${python}" packages/gpt2giga-harness/asset_contract.py --require-clean
    require_lock
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
