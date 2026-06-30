#!/bin/bash
# Run real-model profiling tests, showing [PROFILE] timing lines + test results.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "🚀 Running real-model profiling tests..."
echo ""

uv run pytest tests/integration/real_models/ -v --log-cli-level=INFO -s 2>&1 | grep --color=always -E '(PROFILE|PASSED|FAILED|ERROR|===)'

echo ""
echo "✅ Done"
