#!/bin/bash
# Setup script for the git-convoy virtual environment

cd "$(dirname "$0")"

# Create virtual environment if it doesn't exist
if [ ! -d "gitconvoy-venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv gitconvoy-venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
# shellcheck disable=SC1091
source gitconvoy-venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -e ".[dev]"

echo "Setup complete! To activate the virtual environment, run:"
echo "  source ops/git-convoy/gitconvoy-venv/bin/activate"
echo ""
echo "Then run the CLI with:"
echo "  git convoy --help"
echo "  git-convoy --help"
