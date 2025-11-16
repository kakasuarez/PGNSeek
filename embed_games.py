#!/usr/bin/env python3
"""
Embedding and FAISS Index Builder for Chess Game Retrieval Engine

Loads JSONL game data in batches, generates embeddings using sentence-transformers,
and builds a FAISS index for efficient similarity search.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any
import numpy as np
from tqdm import tqdm
import faiss
from sentence_transformers import SentenceTransformer


class GameEmbedder:
    """Handles embedding generation and FAISS index creation."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the embedder with a sentence-transformer model.

        Args:
            model_name: Name of the sentence-transformer model to use
        """
        print(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        print(f"Model loaded. Embedding dimension: {self.embedding_dim}")

    def load_games_batch(self, jsonl_path: str, batch_size: int = 1000):
        """
        Generator that yields batches of games from JSONL file.

        Args:
            jsonl_path: Path to JSONL file
            batch_size: Number of games per batch

        Yields:
            List of game dictionaries
        """
        batch = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    game = json.loads(line)
                    batch.append(game)

                    if len(batch) >= batch_size:
                        yield batch
                        batch = []

            # Yield remaining games
            if batch:
                yield batch

    def build_index(self, jsonl_path: str, output_dir: str, batch_size: int = 1000):
        """
        Build FAISS index from JSONL game data.

        Args:
            jsonl_path: Path to input JSONL file
            output_dir: Directory to save index and metadata
            batch_size: Batch size for processing
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        index_path = output_path / "faiss_index.bin"
        metadata_path = output_path / "metadata.json"

        print(f"Building FAISS index from: {jsonl_path}")
        print(f"Output directory: {output_dir}")
        print(f"Batch size: {batch_size}")

        # Count total games for progress bar
        print("Counting games...")
        total_games = sum(
            1 for line in open(jsonl_path, "r", encoding="utf-8") if line.strip()
        )
        print(f"Total games to process: {total_games}")

        # Initialize FAISS index (L2 distance)
        index = faiss.IndexFlatL2(self.embedding_dim)

        # Store metadata for each game
        all_metadata = []

        # Process games in batches
        print("\nGenerating embeddings and building index...")
        with tqdm(total=total_games, desc="Processing", unit=" games") as pbar:
            for batch in self.load_games_batch(jsonl_path, batch_size):
                # Extract embedding texts
                embedding_texts = [game["embedding_text"] for game in batch]

                # Generate embeddings
                embeddings = self.model.encode(
                    embedding_texts,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=False,
                )

                # Add to FAISS index
                index.add(embeddings.astype("float32"))

                # Store metadata (without embedding_text to save space)
                for game in batch:
                    metadata = {
                        "white": game["white"],
                        "black": game["black"],
                        "result": game["result"],
                        "eco": game["eco"],
                        "opening": game["opening"],
                        "event": game["event"],
                        "site": game["site"],
                        "date": game["date"],
                        "round": game["round"],
                        "white_elo": game["white_elo"],
                        "black_elo": game["black_elo"],
                        "pgn": game["pgn"],
                        "uci_moves": game["uci_moves"],
                    }
                    all_metadata.append(metadata)

                pbar.update(len(batch))

        # Save FAISS index
        print(f"\nSaving FAISS index to: {index_path}")
        faiss.write_index(index, str(index_path))

        # Save metadata
        print(f"Saving metadata to: {metadata_path}")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(all_metadata, f, ensure_ascii=False, indent=2)

        # Print statistics
        print(f"\n✓ Index building complete!")
        print(f"  Total games indexed: {index.ntotal}")
        print(f"  Embedding dimension: {self.embedding_dim}")
        print(f"  Index file size: {index_path.stat().st_size / (1024**2):.2f} MB")
        print(
            f"  Metadata file size: {metadata_path.stat().st_size / (1024**2):.2f} MB"
        )

        return index, all_metadata


def main():
    """Main entry point for the script."""
    if len(sys.argv) < 3:
        print("Usage: python embed_games.py <input.jsonl> <output_dir> [batch_size]")
        print("\nExample:")
        print("  python embed_games.py games.jsonl ./index")
        print("  python embed_games.py games.jsonl ./index 2000")
        print("\nThis will create:")
        print("  - output_dir/faiss_index.bin")
        print("  - output_dir/metadata.json")
        sys.exit(1)

    jsonl_path = sys.argv[1]
    output_dir = sys.argv[2]
    batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

    # Check if input file exists
    if not Path(jsonl_path).exists():
        print(f"Error: Input file '{jsonl_path}' not found", file=sys.stderr)
        sys.exit(1)

    # Create embedder and build index
    embedder = GameEmbedder()
    embedder.build_index(jsonl_path, output_dir, batch_size)


if __name__ == "__main__":
    main()
