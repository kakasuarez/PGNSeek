import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ResultCard } from "@/components/search/result-card";
import { Card } from "@/components/ui/card";
import { fetchGame, fetchSimilarGames } from "@/lib/api";
import { formatDate, formatResult } from "@/lib/utils";

export function SimilarGamesPage() {
  const params = useParams();
  const gameHash = params.hash || "";
  const navigate = useNavigate();
  const location = useLocation();

  const gameQuery = useQuery({
    queryKey: ["game", gameHash],
    queryFn: () => fetchGame(gameHash),
    enabled: Boolean(gameHash),
  });

  const similarQuery = useQuery({
    queryKey: ["similar-games", gameHash],
    queryFn: () => fetchSimilarGames(gameHash),
    enabled: Boolean(gameHash),
  });

  const similarGames = similarQuery.data ?? [];

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <button
        onClick={() => {
          if (location.key !== "default") {
            navigate(-1);
          } else {
            navigate(`/game/${gameHash}`, { replace: true });
          }
        }}
        className="inline-flex items-center gap-2 text-sm text-[var(--muted)] transition hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to game
      </button>

      <section className="space-y-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">
            Similar games
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
            Games close to this one
          </h1>
        </div>

        {gameQuery.data ? (
          <Card className="rounded-xl border-white/8 bg-[rgba(16,22,29,0.72)] p-4 text-sm text-[var(--muted)]">
            <Link
              to={`/game/${gameQuery.data.game_hash}`}
              className="font-medium text-white transition hover:text-[var(--accent)]"
            >
              {gameQuery.data.opening_name || "Unknown opening"}
            </Link>
            <div className="mt-1">
              {gameQuery.data.white} vs {gameQuery.data.black} ·{" "}
              {formatResult(gameQuery.data.result)} · {formatDate(gameQuery.data.date)}
            </div>
          </Card>
        ) : null}
      </section>

      {similarQuery.isLoading ? (
        <Card className="flex items-center gap-3 rounded-xl border-white/8 bg-[var(--panel)] px-5 py-8 text-sm text-[var(--muted)]">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          Finding similar games...
        </Card>
      ) : null}

      {similarQuery.error ? (
        <Card className="rounded-xl border-amber-500/20 bg-amber-500/8 px-5 py-8 text-sm text-amber-200">
          {(similarQuery.error as Error).message}
        </Card>
      ) : null}

      {!similarQuery.isLoading && !similarQuery.error && !similarGames.length ? (
        <Card className="rounded-xl border-dashed border-white/10 bg-[rgba(16,22,29,0.72)] px-5 py-10 text-sm text-[var(--muted)]">
          No similar games were found for this game yet.
        </Card>
      ) : null}

      {similarGames.length ? (
        <div className="space-y-4">
          <div className="text-sm text-[var(--muted)]">
            {similarGames.length.toLocaleString()} similar games found
          </div>
          <div className="space-y-3">
            {similarGames.map((game) => (
              <ResultCard key={game.game_hash} game={game} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
