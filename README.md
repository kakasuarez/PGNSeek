# PGNSeek: LLM-Powered Chess Game Retrieval Engine

A production-grade semantic search engine for chess games using sentence embeddings and FAISS. Search through hundreds of thousands of chess games using natural language queries.

## 🎯 Features

- **Semantic Search**: Find chess games using natural language queries
- **Efficient Processing**: Stream-based PGN parsing handles millions of games
- **Fast Retrieval**: FAISS-powered vector similarity search
- **REST API**: FastAPI server with automatic documentation
- **Memory Efficient**: Batch processing prevents memory overflow
- **Rich Metadata**: Extracts players, ratings, openings, ECO codes, and moves

## 🏗️ Architecture

```
┌─────────────────┐
│  PGN.zst File   │
└────────┬────────┘
         │ decompress.sh
         ▼
┌─────────────────┐
│   PGN File      │
└────────┬────────┘
         │ parse_pgn.py
         ▼
┌─────────────────┐
│  JSONL Data     │
└────────┬────────┘
         │ embed_games.py
         ▼
┌─────────────────┐
│  FAISS Index    │
│  + Metadata     │
└────────┬────────┘
         │ search.py / main.py
         ▼
┌─────────────────┐
│  Search Results │
└─────────────────┘
```

## 📋 Prerequisites

- Python 3.8+
- zstd (for decompression)
- 4GB+ RAM recommended
- ~500MB disk space per 100k games (varies with dataset)

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install system dependencies
sudo apt-get install zstd  # Ubuntu/Debian
# OR
brew install zstd          # macOS

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Decompress PGN File

```bash
# Make script executable
chmod +x decompress.sh

# Decompress the .zst file
./decompress.sh lichess_db_broadcast_2025-10.pgn.zst
```

This will create `lichess_db_broadcast_2025-10.pgn` in the same directory.

### 3. Parse PGN to JSONL

```bash
# Parse all games
python parse_pgn.py lichess_db_broadcast_2025-10.pgn games.jsonl

# Or parse only first 10,000 games (for testing)
python parse_pgn.py lichess_db_broadcast_2025-10.pgn games.jsonl 10000
```

**Output**: `games.jsonl` with one game per line in JSON format.

### 4. Build FAISS Index

```bash
# Create embeddings and build index
python embed_games.py games.jsonl ./index

# Optional: specify batch size (default: 1000)
python embed_games.py games.jsonl ./index 2000
```

**Output**:

- `index/faiss_index.bin` - FAISS vector index
- `index/metadata.json` - Game metadata

### 5. Test Search (CLI)

```bash
# Search from command line
python search.py "Magnus Carlsen wins with Sicilian Defense" 5

# Search for specific openings
python search.py "Queen's Gambit Declined games" 10

# Search by player and outcome
python search.py "Hikaru Nakamura draw" 5
```

### 6. Run API Server

```bash
# Start FastAPI server
python main.py

# Or with custom settings
python main.py --host 0.0.0.0 --port 8000 --reload
```

**Access**:

- API: http://localhost:8000
- Interactive Docs: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

## 🔍 API Usage

### Search Endpoint (GET)

```bash
curl "http://localhost:8000/search?query=Magnus%20Carlsen%20wins&top_k=5"
```

### Search Endpoint (POST)

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Sicilian Defense games with tactical sacrifices",
    "top_k": 10
  }'
```

### Response Format

```json
{
  "query": "Magnus Carlsen wins",
  "top_k": 5,
  "total_results": 5,
  "results": [
    {
      "rank": 1,
      "white": "Carlsen, Magnus",
      "black": "Nepomniachtchi, Ian",
      "result": "1-0",
      "eco": "C42",
      "opening": "Petrov Defense",
      "event": "World Championship 2021",
      "date": "2021.12.03",
      "white_elo": "2855",
      "black_elo": "2782",
      "similarity_score": 0.8234,
      "pgn": "[Event \"World Championship\"]\n...",
      "uci_moves": ["e2e4", "e7e5", ...]
    }
  ]
}
```

## 📊 Example Queries

- `"Sicilian Defense games"`
- `"Magnus Carlsen wins"`
- `"Queen's Gambit with black victory"`
- `"Rapid games between strong players"`
- `"King's Indian Defense tactical games"`
- `"Endgame with rook and pawn"`
- `"2023 championship games"`
- `"High-rated player draws"`

## 🛠️ Project Structure

```
PGNSeek/
├── decompress.sh              # Shell script to decompress .zst files
├── parse_pgn.py              # PGN parser (PGN → JSONL)
├── embed_games.py            # Embedding generator (JSONL → FAISS)
├── search.py                 # Search module with CLI
├── main.py                   # FastAPI server
├── requirements.txt          # Python dependencies
├── README.md                 # This file
├── lichess_db_broadcast_2025-10.pgn.zst  # Input data (compressed)
├── games.jsonl               # Parsed games (generated)
└── index/                    # FAISS index directory (generated)
    ├── faiss_index.bin       # Vector index
    └── metadata.json         # Game metadata
```

## 🔧 Configuration

### Embedding Model

Default: `all-MiniLM-L6-v2` (384-dimensional embeddings)

To use a different model, modify both `embed_games.py` and `search.py`:

```python
model_name = 'paraphrase-MiniLM-L6-v2'  # or other sentence-transformers model
```

### Batch Size

Adjust batch size based on available RAM:

```bash
# For limited RAM (< 4GB)
python embed_games.py games.jsonl ./index 500

# For more RAM (8GB+)
python embed_games.py games.jsonl ./index 2000
```

### FAISS GPU Support

For GPU acceleration, install `faiss-gpu` instead:

```bash
pip uninstall faiss-cpu
pip install faiss-gpu
```

## 📈 Performance

**Typical Processing Times** (100k games on modest hardware):

- **Decompression**: 1-2 minutes
- **Parsing**: 5-10 minutes
- **Embedding**: 10-20 minutes
- **Search Query**: < 100ms

**Memory Usage**:

- Parsing: ~500MB
- Embedding: ~2GB (with batch_size=1000)
- Search: ~1GB (index loaded in memory)

## 🐛 Troubleshooting

### Import Errors

```bash
# Make sure all dependencies are installed
pip install -r requirements.txt
```

### Memory Issues During Embedding

```bash
# Reduce batch size
python embed_games.py games.jsonl ./index 500
```

### FAISS Index Not Found

```bash
# Ensure you've built the index first
python embed_games.py games.jsonl ./index
```

### Server Won't Start

```bash
# Check if index exists
ls -la index/

# Verify Python environment
python --version
pip list | grep fastapi
```

## 🚦 Development

### Running Tests

```bash
# Test with small dataset
python parse_pgn.py test.pgn test.jsonl 100
python embed_games.py test.jsonl ./test_index
python search.py "test query" 5 ./test_index
```

### Development Mode

```bash
# Run server with auto-reload
python main.py --reload
```

## 📝 Data Format

### JSONL Game Object

```json
{
	"white": "Carlsen, Magnus",
	"black": "Nakamura, Hikaru",
	"result": "1-0",
	"eco": "C42",
	"opening": "Petrov Defense",
	"event": "Speed Chess Championship",
	"site": "chess.com",
	"date": "2023.09.15",
	"round": "1",
	"white_elo": "2855",
	"black_elo": "2794",
	"pgn": "[Event \"Speed Chess\"]\n...",
	"uci_moves": ["e2e4", "e7e5", "g1f3", "g8f6"],
	"embedding_text": "Opening: Petrov Defense. ECO code: C42. White: Carlsen, Magnus. ..."
}
```

## 🎓 How It Works

1. **Parsing**: Stream through PGN file, extract metadata and moves using `python-chess`
2. **Text Generation**: Create rich textual descriptions for semantic search
3. **Embedding**: Convert text to 384-dimensional vectors using sentence-transformers
4. **Indexing**: Store vectors in FAISS L2 index for fast similarity search
5. **Search**: Embed query, find nearest neighbors in FAISS, return metadata

## 🤝 Contributing

Contributions welcome! Areas for improvement:

- [ ] Add support for more embedding models
- [ ] Implement result caching
- [ ] Add filters (date range, player ELO, opening)
- [ ] Batch API endpoint
- [ ] Web UI for search
- [ ] Docker support

## 📄 License

This project is open source and available under the MIT License.

## 🙏 Acknowledgments

- [python-chess](https://python-chess.readthedocs.io/) for PGN parsing
- [sentence-transformers](https://www.sbert.net/) for embeddings
- [FAISS](https://github.com/facebookresearch/faiss) for similarity search
- [FastAPI](https://fastapi.tiangolo.com/) for the API framework
- [Lichess](https://lichess.org/) for chess game databases

## 📧 Support

For issues, questions, or suggestions, please open an issue on GitHub.

---

**Happy Chess Game Searching! ♟️**
