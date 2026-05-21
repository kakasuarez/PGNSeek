const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

export type GameResult = {
  game_hash: string;
  white: string;
  black: string;
  white_elo?: number | null;
  black_elo?: number | null;
  avg_rating?: number | null;
  result?: string | null;
  date?: string | null;
  year?: number | null;
  eco?: string | null;
  opening_name?: string | null;
  num_moves?: number | null;
  avg_material_swings?: number | null;
  piece_sacrifices?: number | null;
  entered_endgame?: boolean | null;
  endgame_move?: number | null;
  endgame_type?: string | null;
  event?: string | null;
  source_file?: string | null;
  pgn_moves?: string | null;
  site?: string | null;
};

export type BucketCount = {
  key: string;
  count: number;
};

export type SearchResponse = {
  results: GameResult[];
  total: number;
  page_size: number;
  cursor?: string | null;
  query_debug: {
    raw_query: string;
    detected_tokens: Record<string, unknown>;
    must_clauses: Array<Record<string, unknown>>;
    filter_clauses: Array<Record<string, unknown>>;
    should_clauses: Array<Record<string, unknown>>;
  };
  aggregations: {
    openings: BucketCount[];
    results: BucketCount[];
    years: BucketCount[];
    eco_categories: BucketCount[];
  };
};

type ApiError = {
  error: string;
  message: string;
  detail?: Record<string, unknown>;
};

async function fetchJson<T>(path: string) {
  const response = await fetch(`${API_URL}${path}`);
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as ApiError;
      message = payload.message || message;
    } catch {
      // ignore invalid JSON error bodies
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function searchGames({
  q,
  cursor,
  pageSize = 20,
}: {
  q: string;
  cursor?: string | null;
  pageSize?: number;
}) {
  const params = new URLSearchParams({
    q,
    page_size: String(pageSize),
  });
  if (cursor) {
    params.set("cursor", cursor);
  }
  return fetchJson<SearchResponse>(`/api/v1/search?${params.toString()}`);
}

export async function fetchGame(gameHash: string) {
  return fetchJson<GameResult>(`/api/v1/games/${gameHash}`);
}

export async function fetchSimilarGames(gameHash: string) {
  return fetchJson<GameResult[]>(`/api/v1/games/${gameHash}/similar`);
}

export { API_URL };
