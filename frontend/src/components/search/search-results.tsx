import { LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResultCard } from "@/components/search/result-card";
import { GameResult, SearchResponse } from "@/lib/api";

export function SearchResults({
  pages,
  isLoading,
  isFetchingNextPage,
  hasNextPage,
  onLoadMore,
}: {
  pages: SearchResponse[] | undefined;
  isLoading: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  onLoadMore: () => void;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-white/8 bg-[var(--panel)] px-4 py-6 text-sm text-[var(--muted)]">
        <LoaderCircle className="h-4 w-4 animate-spin" />
        Searching games...
      </div>
    );
  }

  const results = pages?.flatMap((page) => page.results) ?? [];
  const firstPage = pages?.[0];

  if (!results.length) {
    return (
      <div className="rounded-xl border border-dashed border-white/10 bg-[rgba(16,22,29,0.72)] px-5 py-10 text-sm text-[var(--muted)]">
        No games matched this query yet. Try a player name, opening, result, or rating range.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 text-sm text-[var(--muted)]">
        <div>{firstPage?.total.toLocaleString()} games found</div>
        <div>{results.length.toLocaleString()} loaded</div>
      </div>

      <div className="space-y-3">
        {results.map((game: GameResult) => (
          <ResultCard key={game.game_hash} game={game} />
        ))}
      </div>

      {hasNextPage ? (
        <div className="pt-3">
          <Button
            variant="secondary"
            onClick={onLoadMore}
            disabled={isFetchingNextPage}
            className="min-w-36"
          >
            {isFetchingNextPage ? "Loading..." : "Load more"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
