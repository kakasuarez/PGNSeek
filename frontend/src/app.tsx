import { createBrowserRouter, Outlet } from "react-router-dom";
import { SearchPage } from "@/routes/search-page";
import { GamePage } from "@/routes/game-page";
import { ReviewPage } from "@/routes/review-page";

function RootLayout() {
  return (
    <div className="min-h-screen bg-transparent text-[var(--text)]">
      <header className="sticky top-0 z-20 border-b border-white/6 bg-[rgba(9,13,18,0.85)] backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <a href="/" className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md border border-[var(--panel-border)] bg-[var(--panel)] text-sm font-semibold tracking-[0.2em] text-[var(--accent)]">
              PGN
            </div>
            <div>
              <div className="text-base font-semibold">PGNSeek</div>
              <div className="text-xs text-[var(--muted)]">
                Search and inspect chess games
              </div>
            </div>
          </a>
          <nav className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <a
              href="/"
              className="rounded-md px-3 py-2 transition hover:bg-white/5 hover:text-white"
            >
              Search
            </a>
            <a
              href="/review"
              className="rounded-md px-3 py-2 transition hover:bg-white/5 hover:text-white"
            >
              Review
            </a>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-5 py-8 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <RootLayout />,
    children: [
      { index: true, element: <SearchPage /> },
      { path: "game/:hash", element: <GamePage /> },
      { path: "review", element: <ReviewPage /> },
    ],
  },
]);
