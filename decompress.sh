#!/bin/bash

# Decompress .pgn.zst file to .pgn
# Usage: ./decompress.sh lichess_db_broadcast_2025-10.pgn.zst

if [ $# -eq 0 ]; then
    echo "Usage: $0 <input.pgn.zst>"
    exit 1
fi

INPUT_FILE="$1"
OUTPUT_FILE="${INPUT_FILE%.zst}"

if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: File '$INPUT_FILE' not found"
    exit 1
fi

echo "Decompressing $INPUT_FILE to $OUTPUT_FILE..."
echo "This may take several minutes depending on file size..."

# Use zstd to decompress
# -d: decompress
# -v: verbose output
# --rm: remove source file after successful decompression (optional, remove this flag to keep original)
zstd -d -v "$INPUT_FILE"

if [ $? -eq 0 ]; then
    echo "✓ Decompression complete: $OUTPUT_FILE"
else
    echo "✗ Decompression failed"
    exit 1
fi
