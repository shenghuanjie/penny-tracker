#!/bin/bash

# Check if inp

INPUT_FILE="rebel_final_report.csv"
# If no output file is specified, replace .csv extension with .tsv
OUTPUT_FILE="rebel_final_report.tsv"

# Use python to parse correctly
python3 -c '
import csv, sys

# Setup input and output streams
reader = csv.reader(sys.stdin)
writer = csv.writer(sys.stdout, delimiter="\t")

# Convert
for row in reader:
    writer.writerow(row)
' < "$INPUT_FILE" > "$OUTPUT_FILE"

echo "Converted $INPUT_FILE to $OUTPUT_FILE"
