$MinMajor = 3
$MinMinor = 10

Write-Host "🔍 Checking for Python >= $MinMajor.$MinMinor ..."

# Prefer uv for fast, hassle-free setup.
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
    Write-Host "✅ Found uv — using it for setup"
    uv sync
    Write-Host ""
    Write-Host "🎉 Podvoice is ready!"
    Write-Host "👉 Run: .venv\Scripts\Activate.ps1"
    Write-Host "👉 Then: podvoice --help"
    Write-Host "👉 Or just: uv run podvoice --help"
    exit 0
}

# Fallback: plain venv + pip.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "❌ Python not found. Install Python 3.10 or newer."
    exit 1
}

$versionInfo = python -c "import sys; print(sys.version_info.major, sys.version_info.minor)"
$parts = $versionInfo.Split(" ")
$major = [int]$parts[0]
$minor = [int]$parts[1]

if ($major -lt $MinMajor -or ($major -eq $MinMajor -and $minor -lt $MinMinor)) {
    Write-Host "❌ Python >= $MinMajor.$MinMinor required. Found $major.$minor"
    exit 1
}

Write-Host "✅ Python $major.$minor detected"

Write-Host "📦 Creating virtual environment..."
python -m venv .venv

Write-Host "⚙️ Activating virtual environment..."
. .\.venv\Scripts\Activate.ps1

Write-Host "⬇️ Installing dependencies..."
python -m pip install --upgrade pip
pip install -e .

Write-Host ""
Write-Host "🎉 Podvoice is ready!"
Write-Host "👉 Run: .venv\Scripts\Activate.ps1"
Write-Host "👉 Then: podvoice --help"