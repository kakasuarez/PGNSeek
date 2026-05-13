import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { BoardViewer } from "@/components/game/board-viewer";
import { GameHeader } from "@/components/game/game-header";
import { Card } from "@/components/ui/card";
import { fetchGame } from "@/lib/api";

export function GamePage() {
  const params = useParams();
  const gameHash = params.hash || "";
  const gameQuery = useQuery({
    queryKey: ["game", gameHash],
    queryFn: () => fetchGame(gameHash),
    enabled: Boolean(gameHash),
  });

  return (
    <div className="space-y-5">
      <Link
        to="/"
        className="inline-flex items-center gap-2 text-sm text-[var(--muted)] transition hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to search
      </Link>

      {gameQuery.isLoading ? (
        <Card className="rounded-xl border-white/8 bg-[var(--panel)] px-5 py-10 text-sm text-[var(--muted)]">
          Loading game...
        </Card>
      ) : null}

      {gameQuery.error ? (
        <Card className="rounded-xl border-amber-500/20 bg-amber-500/8 px-5 py-10 text-sm text-amber-200">
          {(gameQuery.error as Error).message}
        </Card>
      ) : null}

      {gameQuery.data ? (
        <>
          <GameHeader game={gameQuery.data} />
          <BoardViewer pgnMoves={gameQuery.data.pgn_moves} />
        </>
      ) : null}
    </div>
  );
}
