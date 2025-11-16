#!/bin/bash

# Setup script for PGNSeek Chess Game Retrieval Engine
# Run this once after cloning the repository

echo "🚀 Setting up PGNSeek Chess Game Retrieval Engine..."
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"
echo ""

# Install system dependencies
echo "Checking system dependencies..."
if ! command -v zstd &> /dev/null; then
    echo "⚠️  zstd not found. Please install it:"
    echo "   Ubuntu/Debian: sudo apt-get install zstd"
    echo "   macOS: brew install zstd"
    echo ""
else
    echo "✓ zstd is installed"
    echo ""
fi

# Create virtual environment
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
echo "✓ Virtual environment activated"
echo ""

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Python dependencies installed"
echo ""

# Make shell scripts executable
echo "Making scripts executable..."
chmod +x decompress.sh
echo "✓ Scripts are now executable"
echo ""

# Create index directory
echo "Creating index directory..."
mkdir -p index
echo "✓ Index directory created"
echo ""

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Decompress your PGN file:"
echo "   ./decompress.sh lichess_db_broadcast_2025-10.pgn.zst"
echo ""
echo "2. Parse the PGN file:"
echo "   python parse_pgn.py lichess_db_broadcast_2025-10.pgn games.jsonl"
echo ""
echo "3. Build the FAISS index:"
echo "   python embed_games.py games.jsonl ./index"
echo ""
echo "4. Test search:"
echo "   python search.py 'Magnus Carlsen wins' 5"
echo ""
echo "5. Start the API server:"
echo "   python main.py"
echo ""
echo "For more information, see README.md"
