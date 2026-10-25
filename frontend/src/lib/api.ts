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

// Opening review report — mirrors backend/app/review/report.py.
// All evaluations are from the reviewed player's point of view.

export type ReviewScore = { cp: number | null; mate: number | null };

export type ReviewClassification = "inaccuracy" | "mistake" | "blunder";

export type ReviewPlayedMove = {
  count: number;
  // Scoring fields are only present on positions where the player is to move
  evaluation?: ReviewScore;
  loss_cp?: number;
  win_chance_loss?: number;
  classification?: ReviewClassification | null;
};

export type ReviewPosition = {
  fen: string;
  side_to_move: "white" | "black";
  player_to_move: boolean;
  occurrences: number;
  wins: number;
  draws: number;
  line: string[];
  best_move: string | null;
  evaluation: (ReviewScore & { depth: number; source: string }) | null;
  played_moves: Record<string, ReviewPlayedMove>;
};

export type ReviewMistake = {
  fen: string;
  line: string[];
  move: string;
  count: number;
  best_move: string | null;
  evaluation_before: ReviewScore;
  evaluation_after: ReviewScore;
  loss_cp: number;
  win_chance_loss: number;
  classification: ReviewClassification;
  impact: number;
};

export type ReviewRepertoire = {
  games: number;
  counts: Record<ReviewClassification, number>;
  positions: Record<string, ReviewPosition>;
  mistakes: ReviewMistake[];
};

export type ReviewReport = {
  summary: {
    player: string;
    games_included: number;
    games_skipped: number;
    max_plies: number;
  };
  repertoires: Record<"white" | "black", ReviewRepertoire>;
};

export async function submitReview(file: File, player: string) {
  const formData = new FormData();
  formData.append("pgn_file", file);
  formData.append("player", player);

  const response = await fetch(`${API_URL}/api/v1/review`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? body?.message ?? `Upload failed: ${response.statusText}`);
  }
  return response.json() as Promise<{ status: string; job_id: string }>;
}

export async function fetchReviewStatus(jobId: string) {
  return fetchJson<{ job_id: string; status: string; error?: string }>(`/api/v1/review/${jobId}`);
}

export async function fetchReviewReports(jobId: string) {
  return fetchJson<{ job_id: string; report: ReviewReport }>(`/api/v1/review/${jobId}/reports`);
}
