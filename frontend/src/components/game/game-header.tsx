import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { GameResult } from "@/lib/api";
import {
  formatDate,
  formatElo,
  formatResult,
  titleCaseEndgame,
} from "@/lib/utils";

export function GameHeader({ game }: { game: GameResult }) {
  const endgame = titleCaseEndgame(game.endgame_type);

  return (
    <Card className="rounded-xl border-white/8 bg-[rgba(16,22,29,0.92)] p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xl font-semibold text-white">
            {game.opening_name || "Unknown opening"}
          </div>
          <div className="mt-2 text-sm text-[var(--muted)]">
            {game.white} ({formatElo(game.white_elo)}) vs {game.black} (
            {formatElo(game.black_elo)})
          </div>
          <div className="mt-2 text-sm text-[var(--muted)]">
            {formatResult(game.result)} · {formatDate(game.date)} ·{" "}
            {game.event || "Unknown event"}
          </div>
        </div>
        <div className="flex flex-col items-start gap-3 text-sm text-[var(--muted)] sm:items-end">
          <div className="text-left sm:text-right">
            <div className="text-base font-semibold text-[var(--accent)]">
              {game.eco || "ECO?"}
            </div>
            <div className="mt-1">Hash: {game.game_hash.slice(0, 12)}</div>
          </div>
          <Link
            to={`/game/${game.game_hash}/similar`}
            className={buttonVariants({ variant: "secondary", size: "sm" })}
          >
            <Search className="h-4 w-4" />
            Find similar games
          </Link>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {endgame ? <Badge variant="accent">Endgame: {endgame}</Badge> : null}
        {game.num_moves ? <Badge variant="warm">{game.num_moves} moves</Badge> : null}
      </div>
    </Card>
  );
}
