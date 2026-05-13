import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { GameResult } from "@/lib/api";
import {
  formatDate,
  formatElo,
  formatResult,
  titleCaseEndgame,
} from "@/lib/utils";

export function ResultCard({ game }: { game: GameResult }) {
  const endgame = titleCaseEndgame(game.endgame_type);

  return (
    <Link to={`/game/${game.game_hash}`} className="block">
      <Card className="group rounded-xl border-white/8 bg-[rgba(16,22,29,0.92)] p-5 transition hover:border-[rgba(110,231,183,0.24)] hover:bg-[rgba(19,27,35,0.96)]">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="truncate text-lg font-semibold text-white">
              {game.opening_name || "Unknown opening"}
            </div>
            <div className="mt-1 text-sm text-[var(--muted)]">
              {game.white} ({formatElo(game.white_elo)}) vs {game.black} (
              {formatElo(game.black_elo)})
            </div>
          </div>
          <div className="shrink-0 text-sm font-medium text-[var(--accent)]">
            {game.eco || "ECO?"}
          </div>
        </div>

        <div className="mt-3 text-sm text-[var(--muted)]">
          {formatResult(game.result)} · {formatDate(game.date)} ·{" "}
          {game.event || "Unknown event"}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {endgame ? (
            <Badge variant="accent" className="text-[11px]">
              Endgame: {endgame}
            </Badge>
          ) : null}
          {game.num_moves ? (
            <Badge variant="warm" className="text-[11px]">
              {game.num_moves} moves
            </Badge>
          ) : null}
        </div>
      </Card>
    </Link>
  );
}
