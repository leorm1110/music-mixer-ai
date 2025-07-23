#!/usr/bin/env bash
# exit on error
set -o errexit

# --- Diagnostic Commands ---
echo "PYTHON_VERSION: $PYTHON_VERSION"
echo "Python version used by build process:"
python --version

# --- Installation ---
pip install --upgrade pip
pip install -r requirements.txt
