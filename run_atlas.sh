#!/usr/bin/env bash
# ATLAS Auto Forge Launcher
set -e

cd "$(dirname "$0")"

# Create virtual env if needed
if [ ! -d "atlas_venv" ]; then
    echo "Setting up ATLAS virtual environment..."
    python3 -m venv atlas_venv
fi

source atlas_venv/bin/activate
pip install -q -r requirements.txt

mkdir -p atlas_data

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "  ERROR: Set your API key first:"
    echo "  export ANTHROPIC_API_KEY=sk-ant-..."
    echo ""
    exit 1
fi

python atlas_app.py run "$@"
