#!/usr/bin/env python3
"""
Quick example script demonstrating the search functionality.
"""

from search import GameSearchEngine


def main():
    """Run example searches."""

    print("=" * 80)
    print("PGNSeek Chess Game Retrieval Engine - Example Usage")
    print("=" * 80)
    print()

    # Initialize search engine
    print("Loading search engine...")
    try:
        engine = GameSearchEngine(index_dir="./index")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nPlease build the index first:")
        print("  python embed_games.py games.jsonl ./index")
        return

    print()

    # Example queries
    example_queries = [
        ("Sicilian Defense games", 3),
        ("Magnus Carlsen wins", 3),
        ("Queen's Gambit with tactical play", 3),
    ]

    for query, top_k in example_queries:
        print("=" * 80)
        print(f"Query: '{query}'")
        print(f"Retrieving top {top_k} results...")
        print("=" * 80)
        print()

        try:
            results = engine.search_games(query, top_k)

            for i, game in enumerate(results, 1):
                print(f"Result {i}:")
                print(f"  Players: {game['white']} vs {game['black']}")
                print(f"  Result: {game['result']}")
                if game["opening"]:
                    print(f"  Opening: {game['opening']}")
                if game["eco"]:
                    print(f"  ECO: {game['eco']}")
                print(f"  Similarity: {game['similarity_score']:.4f}")
                print()

        except Exception as e:
            print(f"Error during search: {e}")

        print()

    print("=" * 80)
    print("Example complete!")
    print()
    print("To run your own searches:")
    print("  python search.py 'your query here' 10")
    print()
    print("To start the API server:")
    print("  python main.py")
    print("=" * 80)


if __name__ == "__main__":
    main()
