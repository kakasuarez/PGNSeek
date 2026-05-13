import { useInfiniteQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { SearchForm } from "@/components/search/search-form";
import { SearchResults } from "@/components/search/search-results";
import { searchGames } from "@/lib/api";

export function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";

  const searchQuery = useInfiniteQuery({
    queryKey: ["search", query],
    queryFn: ({ pageParam }) =>
      searchGames({
        q: query,
        cursor: pageParam as string | null,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.cursor || undefined,
    enabled: query.trim().length > 0,
  });

  function handleSubmit(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set("q", value);
    } else {
      next.delete("q");
    }
    setSearchParams(next);
  }

  return (
    <div className="space-y-8">
      <section className="mx-auto flex max-w-4xl flex-col items-center gap-5 pt-8 text-center">
        <div className="space-y-3">
          <div className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">
            Natural language chess search
          </div>
          <h1 className="text-4xl font-semibold tracking-tight text-white md:text-5xl">
            Find the game you mean.
          </h1>
          <p className="mx-auto max-w-2xl text-sm leading-6 text-[var(--muted)] md:text-base">
            Search by opening, player, style, result, or rating.
          </p>
        </div>

        <div className="w-full">
          <SearchForm initialValue={query} onSubmit={handleSubmit} />
        </div>
      </section>

      {query ? (
        <section className="mx-auto max-w-4xl">
          <SearchResults
            pages={searchQuery.data?.pages}
            isLoading={searchQuery.isLoading}
            isFetchingNextPage={searchQuery.isFetchingNextPage}
            hasNextPage={Boolean(searchQuery.hasNextPage)}
            onLoadMore={() => void searchQuery.fetchNextPage()}
          />
          {searchQuery.error ? (
            <div className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/8 px-4 py-3 text-sm text-amber-200">
              {(searchQuery.error as Error).message}
            </div>
          ) : null}
        </section>
      ) : (
        <section className="mx-auto max-w-4xl rounded-xl border border-white/8 bg-[rgba(16,22,29,0.72)] p-5 text-sm text-[var(--muted)]">
          Try queries like <span className="text-white">Carlsen wins as white</span>,{" "}
          <span className="text-white">Sicilian under 40 moves</span>, or{" "}
          <span className="text-white">positional French 2400+</span>.
        </section>
      )}
    </div>
  );
}
