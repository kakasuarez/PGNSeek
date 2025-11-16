#!/usr/bin/env python3
"""
Search Module for Chess Game Retrieval Engine

Provides semantic search functionality using FAISS index and sentence embeddings.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer


class GameSearchEngine:
    """Semantic search engine for chess games using FAISS."""

    def __init__(self, index_dir: str, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the search engine.

        Args:
            index_dir: Directory containing faiss_index.bin and metadata.json
            model_name: Name of the sentence-transformer model (must match the one used for indexing)
        """
        self.index_dir = Path(index_dir)
        self.model_name = model_name

        # Load FAISS index
        index_path = self.index_dir / "faiss_index.bin"
        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index not found at: {index_path}")

        print(f"Loading FAISS index from: {index_path}")
        self.index = faiss.read_index(str(index_path))
        print(f"Index loaded. Total vectors: {self.index.ntotal}")

        # Load metadata
        metadata_path = self.index_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Metadata not found at: {metadata_path}")

        print(f"Loading metadata from: {metadata_path}")
        with open(metadata_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        print(f"Metadata loaded. Total games: {len(self.metadata)}")

        # Load sentence transformer model
        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        print("Search engine ready!")

    def search_games(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        Search for chess games semantically similar to the query.

        Args:
            query: Natural language search query
            top_k: Number of top results to return

        Returns:
            List of dictionaries containing game metadata and PGN, sorted by relevance
        """
        # Validate inputs
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        # Limit top_k to available games
        top_k = min(top_k, len(self.metadata))

        # Generate query embedding
        query_embedding = self.model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=False
        ).astype("float32")

        # Search FAISS index
        distances, indices = self.index.search(query_embedding, top_k)

        # Collect results with metadata
        results = []
        for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < len(self.metadata):
                game_data = self.metadata[idx].copy()
                game_data["rank"] = i + 1
                game_data["distance"] = float(distance)
                game_data["similarity_score"] = float(
                    1.0 / (1.0 + distance)
                )  # Convert distance to similarity
                results.append(game_data)

        return results

    def format_result(self, game: Dict[str, Any], include_pgn: bool = True) -> str:
        """
        Format a single game result for display.

        Args:
            game: Game metadata dictionary
            include_pgn: Whether to include full PGN text

        Returns:
            Formatted string representation of the game
        """
        lines = []
        lines.append(f"Rank: {game.get('rank', 'N/A')}")
        lines.append(f"Similarity Score: {game.get('similarity_score', 0):.4f}")
        lines.append(f"White: {game['white']} ({game['white_elo'] or 'unrated'})")
        lines.append(f"Black: {game['black']} ({game['black_elo'] or 'unrated'})")
        lines.append(f"Result: {game['result']}")

        if game["opening"]:
            lines.append(f"Opening: {game['opening']}")
        if game["eco"]:
            lines.append(f"ECO: {game['eco']}")
        if game["event"]:
            lines.append(f"Event: {game['event']}")
        if game["date"]:
            lines.append(f"Date: {game['date']}")

        lines.append(f"Moves: {len(game['uci_moves'])}")

        if include_pgn:
            lines.append("\nPGN:")
            lines.append(game["pgn"])

        return "\n".join(lines)


def search_games(
    query: str, top_k: int = 10, index_dir: str = "./index"
) -> List[Dict[str, Any]]:
    """
    Convenience function to search for games without instantiating the class.

    Args:
        query: Natural language search query
        top_k: Number of top results to return
        index_dir: Directory containing FAISS index and metadata

    Returns:
        List of game dictionaries with metadata and PGN
    """
    engine = GameSearchEngine(index_dir)
    return engine.search_games(query, top_k)


def main():
    """Demo usage of the search engine."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python search.py '<query>' [top_k] [index_dir]")
        print("\nExample:")
        print("  python search.py 'Sicilian Defense games' 5")
        print("  python search.py 'Magnus Carlsen wins' 10 ./index")
        sys.exit(1)

    query = sys.argv[1]
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    index_dir = sys.argv[3] if len(sys.argv) > 3 else "./index"

    # Initialize search engine
    engine = GameSearchEngine(index_dir)

    # Perform search
    print(f"\nSearching for: '{query}'")
    print(f"Top {top_k} results:\n")
    print("=" * 80)

    results = engine.search_games(query, top_k)

    for i, game in enumerate(results):
        if i > 0:
            print("\n" + "=" * 80)
        print(engine.format_result(game, include_pgn=False))

    print("\n" + "=" * 80)
    print(f"\nFound {len(results)} matching games")


if __name__ == "__main__":
    main()
