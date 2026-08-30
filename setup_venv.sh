#!/bin/bash
# Setup script for the git-convoy virtual environment.
# Always installs from PyPI. git-convoy has no private packages; a machine
# pip.conf pointed at CodeArtifact must not be used.
set -euo pipefail

cd "$(dirname "$0")"

PYPI_INDEX="https://pypi.org/simple"

# Create virtual environment if it doesn't exist
if [ ! -d "gitconvoy-venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv gitconvoy-venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
# shellcheck disable=SC1091
source gitconvoy-venv/bin/activate

# --isolated ignores user/env pip config (including a CodeArtifact index-url).
echo "Installing dependencies from PyPI..."
pip install --isolated --index-url "$PYPI_INDEX" --upgrade pip
pip install --isolated --index-url "$PYPI_INDEX" -e ".[dev]"

echo "Setup complete! To activate the virtual environment, run:"
echo "  source ops/git-convoy/gitconvoy-venv/bin/activate"
echo ""
echo "Then run the CLI with:"
echo "  git convoy --help"
echo "  git-convoy --help"
