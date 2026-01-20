import os

# --- Configuration ---
INPUT_FILE = "rebel_final_report_backup.tsv"
OUTPUT_FILE = "rebel_final_report.tsv"
TOTAL_ROW_SIZE = 1000  # The exact length you want per line (including newline)


def process_file():
    # We use '\n' as the newline. This is 1 character.
    # Therefore, allowed text length is 1000 - 1 = 999.
    newline_char = '\n'
    text_width = TOTAL_ROW_SIZE - len(newline_char)

    print(f"Starting conversion...")
    print(f"Target: {text_width} chars text + 1 char newline = {TOTAL_ROW_SIZE} total.")

    with open(INPUT_FILE, 'r', encoding='utf-8', errors='replace') as infile, \
            open(OUTPUT_FILE, 'w', encoding='utf-8', newline=newline_char) as outfile:

        count = 0
        for line in infile:
            # 1. Remove existing newlines and carriage returns
            clean_line = line.rstrip('\r\n')

            # 2. Skip empty lines (matching your grep -v logic)
            # If you want to keep empty lines as blank rows of spaces, remove this if-block.
            if not clean_line.strip():
                continue

            # 3. Enforce Length
            if len(clean_line) < text_width:
                # Pad with spaces on the right
                final_line = clean_line.ljust(text_width)
            else:
                # Truncate to strict limit
                final_line = clean_line[:text_width]

            # 4. Write to file
            outfile.write(final_line + newline_char)
            count += 1

    print(f"Successfully processed {count} lines.")


def verify_output():
    print("\nVerifying first all lines...")
    with open(OUTPUT_FILE, 'r', encoding='utf-8', newline='\n') as f:
        for i, line in enumerate(f):
            # if i >= 5: break
            # We use repr() to see hidden characters like \n
            print(f"Line {i + 1}: Length {len(line)} | Ends with newline? {line.endswith(chr(10))}")


if __name__ == "__main__":
    process_file()
    verify_output()
