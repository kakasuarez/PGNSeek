import chess.pgn


def extract_first_n_games(input_pgn, output_pgn, n=50_000):
    with open(input_pgn, "r", encoding="utf-8") as infile, open(
        output_pgn, "w", encoding="utf-8"
    ) as outfile:

        count = 0

        while count < n:
            game = chess.pgn.read_game(infile)

            if game is None:
                break

            print(game, file=outfile, end="\n\n")
            count += 1

        print(f"Extracted {count} games to {output_pgn}")


if __name__ == "__main__":
    input_file = "lichess 50 games.pgn"
    output_file = "first_50_games.pgn"

    extract_first_n_games(input_file, output_file, 50)
