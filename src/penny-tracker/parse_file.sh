#!/bin/bash

INPUT_FILE="rebel_final_report_backup.csv"
OUTPUT_FILE="rebel_final_report.csv"
ROW_SIZE=1000

# Calculate text width (Total Size - 1 byte for the newline)
TEXT_WIDTH=$((ROW_SIZE - 1))

: > "$OUTPUT_FILE"

# Set locale to "C" (High speed, 1 char = 1 byte)
export LC_ALL=C

# 1. tr -d '\r': Deletes invisible Windows carriage returns
# 2. grep -v "^[[:space:]]*$": Removes lines that are empty or just spaces
# 3. while ... : Processes the clean lines
tr -d '\r' < "$INPUT_FILE" | grep -v "^[[:space:]]*$" | while IFS= read -r line; do

    # Safety check: Skip if line became empty after stripping
    if [ -z "$line" ]; then continue; fi

    # Print formatted line
    printf "%-*.*s\n" "$TEXT_WIDTH" "$TEXT_WIDTH" "$line" >> "$OUTPUT_FILE"

done

echo "Done. Verified sizes:"
awk '{ print length($0) + 1 }' "$OUTPUT_FILE" | head -n 5