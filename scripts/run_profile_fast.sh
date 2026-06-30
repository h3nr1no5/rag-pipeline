#!/bin/bash
# Quick profile run — show only PROFILE lines.
set -euo pipefail

cd "$(dirname "$0")/.."

uv run pytest tests/integration/real_models/ -v --log-cli-level=INFO --tb=short -q 2>&1 | grep --color=always 'PROFILE'
