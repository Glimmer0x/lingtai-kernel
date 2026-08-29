#!/usr/bin/env bash
# Build the one supported interpreter for verify_driver_supervisor_execution_e2e.
#
# The probe imports LingTai and the Puffo Driver server in one interpreter.  Do
# not install Puffo's runtime into it: Puffo's MCP 1.x dependency conflicts
# with LingTai's MCP 2.x runtime.  The Driver is supplied as source via
# --puffo-src; agent-client-protocol is its only additional probe dependency.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <venv-dir>" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="$1"
python_bin="$venv_dir/bin/python"

uv venv "$venv_dir"
uv pip install --python "$python_bin" \
  -e "$repo_root" \
  "mcp==2.1.1" \
  "agent-client-protocol==0.10.1"

"$python_bin" - <<'PY'
import importlib.metadata as metadata
from mcp.server import ServerRequestContext  # noqa: F401

assert metadata.version("mcp") == "2.1.1"
assert metadata.version("agent-client-protocol") == "0.10.1"
print("driver_supervisor_e2e_environment=ok mcp=2.1.1 agent-client-protocol=0.10.1")
PY
