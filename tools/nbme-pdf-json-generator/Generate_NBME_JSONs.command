#!/bin/bash
# Generate_NBME_JSONs.command
# Double-click this file in Finder to run the NBME PDF extractor.
# macOS may ask for permission the first time — click Open.

# Change to the directory this script lives in, regardless of where it was launched from.
cd "$(dirname "$0")"

echo "========================================"
echo "  NBME PDF → JSON Generator"
echo "  Milestone 1: Deterministic Extraction"
echo "========================================"
echo ""

# Locate python3
PYTHON=$(which python3 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 not found on PATH."
    echo "Install Python 3 from https://www.python.org/downloads/ and try again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

echo "Using Python: $PYTHON ($($PYTHON --version 2>&1))"
echo ""

# Check pdfplumber is available
$PYTHON -c "import pdfplumber" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "pdfplumber not found — installing..."
    $PYTHON -m pip install pdfplumber --quiet
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install pdfplumber. Run manually:"
        echo "  pip3 install pdfplumber"
        echo ""
        read -p "Press Enter to close..."
        exit 1
    fi
    echo "pdfplumber installed OK."
    echo ""
fi

# Run the extractor
$PYTHON extract_pdfs.py

echo ""
read -p "Done. Press Enter to close this window..."
