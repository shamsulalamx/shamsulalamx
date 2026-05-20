#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo " Images/Tables -> App-Ready JSON"
echo "========================================"
echo ""
PYTHON=$(which python3 2>/dev/null)
if [ -z "$PYTHON" ]; then
  echo "ERROR: python3 not found on PATH."
  read -p "Press Enter to close..."
  exit 1
fi
"$PYTHON" generate_images_tables_questions.py --init
echo ""
"$PYTHON" generate_images_tables_questions.py --generate
STATUS=$?
echo ""
if [ $STATUS -ne 0 ]; then
  echo "Generation failed. See logs/ for details."
else
  echo "Generation complete. Import the JSON from output_json/app_ready/."
fi
read -p "Press Enter to close this window..."
exit $STATUS
