#!/usr/bin/env python3
"""Diagnostic: check how many rows the TSV reader loads vs total lines."""
import sys

FIELDNAMES = ["name", "price", "url", "image", "original_timestamp", "hd_status",
              "updated_at", "padding"]

tsv_path = sys.argv[1] if len(sys.argv) > 1 else "rebel_final_report.tsv"

total_lines = 0
loaded = 0
skipped_empty = 0
skipped_header = 0
short_rows = 0  # rows with fewer than 7 fields
field_counts = {}

with open(tsv_path, "r", encoding="utf-8") as f:
    header = f.readline()
    print(f"Header fields: {len(header.strip().split(chr(9)))}")
    for line_num, row in enumerate(f, start=2):
        total_lines += 1
        parts = row.strip().split("\t")
        parts = [p.strip() for p in parts]
        n_fields = len(parts)
        field_counts[n_fields] = field_counts.get(n_fields, 0) + 1

        if not parts or not parts[0]:
            skipped_empty += 1
            continue
        if parts[0] == "name":
            skipped_header += 1
            continue
        if n_fields < 7:
            short_rows += 1
            print(f"  Line {line_num}: only {n_fields} fields: {parts[0][:60]}...")
        loaded += 1

print(f"\nTotal data lines: {total_lines}")
print(f"Loaded: {loaded}")
print(f"Skipped (empty): {skipped_empty}")
print(f"Skipped (header): {skipped_header}")
print(f"Short rows (<7 fields): {short_rows}")
print(f"\nField count distribution:")
for k in sorted(field_counts.keys()):
    print(f"  {k} fields: {field_counts[k]} rows")
