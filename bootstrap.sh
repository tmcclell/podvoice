#!/usr/bin/env bash
set -e

MIN_MAJOR=3
MIN_MINOR=10

echo "🔍 Checking for Python >= ${MIN_MAJOR}.${MIN_MINOR} ..."

# Prefer uv for fast, hassle-free setup.
if command -v uv >/dev/null 2>&1; then
  echo "✅ Found uv — using it for setup"
  uv sync
  echo ""
  echo "🎉 Podvoice is ready!"
  echo "👉 Run: source .venv/bin/activate"
  echo "👉 Then: podvoice --help"
  echo "👉 Or just: uv run podvoice --help"
  exit 0
fi

# Fallback: plain venv + pip.
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "❌ Python not found. Please install Python 3.10 or newer."
  exit 1
fi

MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')

if [ "$MAJOR" -lt "$MIN_MAJOR" ] || { [ "$MAJOR" -eq "$MIN_MAJOR" ] && [ "$MINOR" -lt "$MIN_MINOR" ]; }; then
  echo "❌ Python >= ${MIN_MAJOR}.${MIN_MINOR} required. Found Python ${MAJOR}.${MINOR}."
  exit 1
fi

echo "✅ Python ${MAJOR}.${MINOR} detected"

echo "📦 Creating virtual environment..."
$PYTHON -m venv .venv

echo "⚙️ Activating virtual environment..."
source .venv/bin/activate

echo "⬇️ Installing dependencies..."
pip install --upgrade pip
pip install -e .

echo ""
echo "🎉 Podvoice is ready!"
echo "👉 Run: source .venv/bin/activate"
echo "👉 Then: podvoice --help"