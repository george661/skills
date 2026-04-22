#!/bin/bash
#
# Create a per-worktree Python .venv with uv and install editable packages.
# Run from the worktree root (or main checkout). Safe to re-run — uv is idempotent.
#
# Why: editable installs into a shared interpreter (miniconda base, system python)
# cause one worktree's `pip install -e .` to shadow every other worktree using the
# same interpreter. A local .venv per worktree pins imports to that worktree's src.
#
# Usage:
#   ./scripts/setup-venv.sh              # create .venv + install packages[dev]
#   ./scripts/setup-venv.sh --python 3.9 # pin interpreter version

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

PYTHON_VERSION="3.12"
if [[ "${1:-}" == "--python" && -n "${2:-}" ]]; then
    PYTHON_VERSION="$2"
fi

if ! command -v uv &>/dev/null; then
    echo "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

cd "$REPO_DIR"

if [[ ! -d .venv ]]; then
    uv venv .venv --python "$PYTHON_VERSION"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

install_args=()
for pkg_dir in packages/*/; do
    if [[ -f "${pkg_dir}pyproject.toml" ]]; then
        install_args+=(-e "${pkg_dir%/}[dev]")
    fi
done

if [[ ${#install_args[@]} -eq 0 ]]; then
    echo "No packages/ with pyproject.toml found in $REPO_DIR" >&2
    exit 1
fi

uv pip install "${install_args[@]}"

echo ""
echo "Done. Activate this worktree's venv with:"
echo "  source $REPO_DIR/.venv/bin/activate"
echo ""
echo "Verify the editable install points at this worktree:"
echo "  python -c 'import dag_dashboard; print(dag_dashboard.__file__)'"
