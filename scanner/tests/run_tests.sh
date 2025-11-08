#!/bin/bash
# Run scanner tests with pytest

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

echo "Running scanner tests with pytest..."
echo ""

# Check if pytest is installed
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "Installing pytest..."
    pip3 install pytest pytest-cov
    echo ""
fi

# Run pytest
pytest -v --tb=short

exit $?

