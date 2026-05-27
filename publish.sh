#!/usr/bin/env bash
set -e

echo "Building AGeval SDK..."
python3 -m pip install --upgrade build twine
python3 -m build

echo ""
echo "Checking distribution..."
python3 -m twine check dist/*

echo ""
echo "Publishing to PyPI..."
echo "You will be prompted for your PyPI username (usually __token__) and password (your API token)."
python3 -m twine upload dist/*

echo ""
echo "✅ Published successfully!"
