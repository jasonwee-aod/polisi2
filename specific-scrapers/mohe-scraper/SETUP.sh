#!/bin/bash
# Setup script for MOHE Scraper
# Usage: ./SETUP.sh

set -e

echo "=========================================="
echo "MOHE Scraper Setup"
echo "=========================================="

# Check Python version
echo "Checking Python version..."
python3 --version
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
required_version="3.11"

if [[ $(echo -e "$python_version\n$required_version" | sort -V | head -n1) != "$required_version" ]]; then
    echo "ERROR: Python $required_version+ required (found $python_version)"
    exit 1
fi

echo "✓ Python version OK"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
echo "✓ pip upgraded"

# Install dependencies
echo "Installing dependencies..."
pip install -e . > /dev/null 2>&1
echo "✓ Dependencies installed"

# Install dev dependencies
echo "Installing development tools..."
pip install -e ".[dev]" > /dev/null 2>&1
echo "✓ Development tools installed"

# Create .env if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "✓ .env created (edit if using GCS)"
else
    echo "✓ .env already exists"
fi

# Create data directory
echo "Creating data directories..."
mkdir -p data/manifests/mohe data/documents
echo "✓ Directories created"

# Run tests
echo ""
echo "Running tests..."
pytest tests/ -q
if [ $? -eq 0 ]; then
    echo "✓ All tests passed"
else
    echo "⚠ Some tests failed (see output above)"
fi

# Print next steps
echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Review configuration:"
echo "   cat configs/mohe_site_config.yaml"
echo ""
echo "2. Run a dry-run scrape:"
echo "   mohe-scraper --dry-run --log-level INFO"
echo ""
echo "3. Run full scrape:"
echo "   mohe-scraper"
echo ""
echo "4. View results:"
echo "   cat data/manifests/mohe/records.jsonl | head"
echo ""
echo "5. Read the operator runbook:"
echo "   cat RUNBOOK.md"
echo ""
echo "Optional: Configure Google Cloud Storage"
echo "   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json"
echo "   export GCS_BUCKET=my-bucket"
echo "   mohe-scraper"
echo ""
echo "For help, see:"
echo "  - README.md (overview & features)"
echo "  - RUNBOOK.md (setup & troubleshooting)"
echo "  - PROJECT_SUMMARY.md (what was built)"
echo ""
