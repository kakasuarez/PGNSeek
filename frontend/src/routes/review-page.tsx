import { useState, useEffect, useMemo } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Chess } from "chess.js";
import { Chessboard } from "react-chessboard";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  submitReview,
  fetchReviewStatus,
  fetchReviewReports,
  fetchReviewPosition,
  fetchReviewPositions,
  type ReviewClassification,
  type ReviewMistake,
  type ReviewPosition,
  type ReviewReport,
} from "@/lib/api";
import {
  childFens,
  formatEval,
  formatMoveNumber,
  lineFens,
  normalizeFen,
  toMoveObject,
  uciToSan,
} from "@/lib/chess";
import { useKeyboardShortcuts } from "@/components/game/use-keyboard-shortcuts";

type Color = "white" | "black";

// Children prefetched per position, most played first (matches the backend's MAX_CHILDREN)
const PREFETCH_CHILDREN = 8;

// Cached per position; null means no game reached it. A review's tree never changes, so it never goes stale.
function positionKey(jobId: string | null, color: Color, fen: string) {
  return ["review-position", jobId, color, fen] as const;
}

// Fetches the positions not yet cached and caches them, including null for those no game reached
async function prefetchPositions(queryClient: QueryClient, jobId: string, color: Color, fens: string[]) {
  const missing = [...new Set(fens)].filter(
    (fen) => queryClient.getQueryData(positionKey(jobId, color, fen)) === undefined,
  );
  if (missing.length === 0) return;
  const { positions } = await fetchReviewPositions(jobId, color, missing);
  for (const fen of missing) {
    queryClient.setQueryData(positionKey(jobId, color, fen), positions[fen] ?? null);
  }
}

const CLASSIFICATION_STYLES: Record<ReviewClassification, string> = {
  inaccuracy: "border-[rgba(251,191,36,0.3)] bg-[rgba(251,191,36,0.12)] text-[var(--warning)]",
  mistake: "border-[rgba(251,146,60,0.35)] bg-[rgba(251,146,60,0.14)] text-orange-300",
  blunder: "border-[rgba(248,113,113,0.4)] bg-[rgba(248,113,113,0.15)] text-red-300",
};

const CLASSIFICATIONS: ReviewClassification[] = ["blunder", "mistake", "inaccuracy"];

const PLURALS: Record<ReviewClassification, string> = {
  inaccuracy: "inaccuracies",
  mistake: "mistakes",
  blunder: "blunders",
};

function ClassificationChip({ classification, count }: { classification: ReviewClassification; count?: number }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-[0.08em] ${CLASSIFICATION_STYLES[classification]}`}
    >
      {count !== undefined ? `${count} ${count === 1 ? classification : PLURALS[classification]}` : classification}
    </span>
  );
}

function formatLoss(lossCp: number) {
  return `-${(lossCp / 100).toFixed(1)}`;
}

export function ReviewPage() {
  const [file, setFile] = useState<File | null>(null);
  const [player, setPlayer] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [color, setColor] = useState<Color>("white");
  // The mistake last opened from the list, drawn as a red arrow while its position is on the board
  const [focusedMistake, setFocusedMistake] = useState<ReviewMistake | null>(null);

  const [historyFens, setHistoryFens] = useState<string[]>([new Chess().fen()]);
  const [historySans, setHistorySans] = useState<string[]>([]);
  const [plyIndex, setPlyIndex] = useState(0);

  const decrementPly = () => setPlyIndex((value) => Math.max(0, value - 1));
  const incrementPly = () => setPlyIndex((value) => Math.min(historyFens.length - 1, value + 1));

  useKeyboardShortcuts(decrementPly, ["ArrowLeft"]);
  useKeyboardShortcuts(incrementPly, ["ArrowRight"]);

  const currentFen = historyFens[plyIndex];

  const currentNormalizedFen = useMemo(() => normalizeFen(currentFen), [currentFen]);

  const queryClient = useQueryClient();
  const repertoire = report?.repertoires[color];

  const positionQuery = useQuery({
    queryKey: positionKey(jobId, color, currentNormalizedFen),
    queryFn: async (): Promise<ReviewPosition | null> => {
      const { position, children } = await fetchReviewPosition(jobId!, color, currentNormalizedFen);
      // The response also carries the most played next positions: cache them so clicking one is instant
      for (const child of children) {
        if (queryClient.getQueryData(positionKey(jobId, color, child.fen)) === undefined) {
          queryClient.setQueryData(positionKey(jobId, color, child.fen), child);
        }
      }
      return position;
    },
    enabled: !!report && !!jobId,
    staleTime: Infinity,
    gcTime: 30 * 60_000,
  });
  const currentStats = positionQuery.data;

  // Keep one move ahead: when the current position came from the cache, its children may not be cached yet
  useEffect(() => {
    if (!jobId || !currentStats) return;
    const moves = Object.entries(currentStats.played_moves)
      .sort((a, b) => b[1].count - a[1].count)
      .slice(0, PREFETCH_CHILDREN)
      .map(([uci]) => uci);
    prefetchPositions(queryClient, jobId, color, childFens(currentStats.fen, moves)).catch((err) =>
      console.error(err),
    );
  }, [currentStats, jobId, color, queryClient]);

  useEffect(() => {
    if (!jobId || status === "completed" || status === "failed" || status === "error") return;

    const interval = setInterval(async () => {
      try {
        const res = await fetchReviewStatus(jobId);
        setStatus(res.status);
        if (res.status === "failed") {
          setError(res.error ?? "Review failed.");
        }
        if (res.status === "completed") {
          const reportRes = await fetchReviewReports(jobId);
          const { white, black } = reportRes.report.repertoires;
          setColor(black.games > white.games ? "black" : "white");
          setReport(reportRes.report);
        }
      } catch (err) {
        console.error(err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [jobId, status]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !player) return;
    try {
      setError(null);
      setStatus("uploading...");
      const res = await submitReview(file, player);
      setJobId(res.job_id);
      setStatus(res.status);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Upload failed.");
      setStatus("error");
    }
  }

  function playMove(uci: string) {
    const tempChess = new Chess(historyFens[plyIndex]);
    try {
      const move = tempChess.move({
        from: uci.substring(0, 2),
        to: uci.substring(2, 4),
        promotion: uci[4],
      });
      if (move) {
        const newFens = historyFens.slice(0, plyIndex + 1);
        const newSans = historySans.slice(0, plyIndex);
        newFens.push(tempChess.fen());
        newSans.push(move.san);
        setHistoryFens(newFens);
        setHistorySans(newSans);
        setPlyIndex(plyIndex + 1);
        return true;
      }
    } catch {
      return false;
    }
    return false;
  }

  function onDrop(sourceSquare: string, targetSquare: string, piece: string) {
    return playMove(`${sourceSquare}${targetSquare}${piece[1]?.toLowerCase() ?? ""}`);
  }

  function resetBoard() {
    setHistoryFens([new Chess().fen()]);
    setHistorySans([]);
    setPlyIndex(0);
  }

  // Replays a line of UCI moves from the start position onto the board
  function loadLine(line: string[]) {
    const chess = new Chess();
    const fens = [chess.fen()];
    const sans: string[] = [];
    for (const uci of line) {
      try {
        sans.push(chess.move(toMoveObject(uci)).san);
      } catch {
        break;
      }
      fens.push(chess.fen());
    }
    setHistoryFens(fens);
    setHistorySans(sans);
    setPlyIndex(fens.length - 1);
  }

  async function openMistake(mistake: ReviewMistake) {
    setFocusedMistake(mistake);
    // One request for every position along the line, so stepping through it needs no more
    try {
      await prefetchPositions(queryClient, jobId!, color, lineFens(mistake.line));
    } catch (err) {
      console.error(err);
    }
    loadLine(mistake.line);
  }

  function switchRepertoire(next: Color) {
    setColor(next);
    setFocusedMistake(null);
    resetBoard();
  }

  const arrows = useMemo(() => {
    const result: [string, string, string][] = [];
    if (currentStats?.best_move) {
      result.push([currentStats.best_move.substring(0, 2), currentStats.best_move.substring(2, 4), "rgba(110, 231, 183, 0.75)"]);
    }
    if (focusedMistake && focusedMistake.fen === currentNormalizedFen) {
      result.push([focusedMistake.move.substring(0, 2), focusedMistake.move.substring(2, 4), "rgba(248, 113, 113, 0.75)"]);
    }
    return result;
  }, [currentStats, focusedMistake, currentNormalizedFen]);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-white">Opening Review</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {report
            ? `${report.summary.player}: ${report.summary.games_included} games reviewed, first ${report.summary.max_plies} plies` +
              (report.summary.games_skipped > 0
                ? ` · ${report.summary.games_skipped} skipped (player not found or custom start position)`
                : "")
            : "Upload your PGN to build an opening tree and find the mistakes you keep repeating."}
        </p>
      </div>

      {!jobId || status === "error" || status === "failed" ? (
        <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-6">
          {error && (
            <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}
          <form onSubmit={handleUpload} className="flex flex-col gap-4 max-w-md">
            <div>
              <label className="block text-sm text-[var(--muted)] mb-1">PGN File</label>
              <input
                type="file"
                accept=".pgn"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="text-sm text-white"
                required
              />
            </div>
            <div>
              <label className="block text-sm text-[var(--muted)] mb-1">Player Name</label>
              <input
                type="text"
                value={player}
                onChange={(e) => setPlayer(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-transparent px-3 py-2 text-sm text-white"
                placeholder="Your username"
                required
              />
            </div>
            <button
              type="submit"
              className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-black transition hover:opacity-90"
            >
              Analyze PGN
            </button>
          </form>
        </Card>
      ) : status !== "completed" || !report || !repertoire ? (
        <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-6">
          <div className="text-sm text-white">Job Status: <span className="font-semibold text-[var(--accent)]">{status}</span></div>
        </Card>
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row">
          <div className="w-full max-w-[480px] shrink-0 space-y-4">
            <div className="flex gap-2" role="group" aria-label="Repertoire">
              {(["white", "black"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => switchRepertoire(option)}
                  aria-pressed={color === option}
                  className={`flex-1 rounded-md border px-3 py-1.5 text-sm transition ${
                    color === option
                      ? "border-[rgba(110,231,183,0.35)] bg-[var(--accent-muted)] text-white"
                      : "border-white/10 text-[var(--muted)] hover:bg-white/5 hover:text-white"
                  }`}
                >
                  As {option === "white" ? "White" : "Black"} ({report.repertoires[option].games})
                </button>
              ))}
            </div>
            <Chessboard
              position={currentFen}
              onPieceDrop={onDrop}
              boardOrientation={color}
              customDarkSquareStyle={{ backgroundColor: "#3f4a56" }}
              customLightSquareStyle={{ backgroundColor: "#e0e3e6" }}
              customArrows={arrows as any}
            />
            <div className="flex items-center justify-between gap-3">
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={decrementPly}
                  disabled={plyIndex === 0}
                  aria-label="Previous move"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="secondary"
                  size="icon"
                  onClick={incrementPly}
                  disabled={plyIndex === historyFens.length - 1}
                  aria-label="Next move"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
              <button
                onClick={resetBoard}
                className="rounded-md border border-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/5 transition"
              >
                Reset
              </button>
            </div>
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-6">
            <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-white">Your recurring mistakes</h2>
                <div className="flex flex-wrap gap-1.5">
                  {CLASSIFICATIONS.map((classification) => (
                    <ClassificationChip
                      key={classification}
                      classification={classification}
                      count={repertoire.counts[classification]}
                    />
                  ))}
                </div>
              </div>
              <Separator className="mb-3 border-white/10" />
              {repertoire.games === 0 ? (
                <div className="text-sm italic text-[var(--muted)]">
                  No games as {color} in this PGN.
                </div>
              ) : repertoire.mistakes.length === 0 ? (
                <div className="text-sm italic text-[var(--muted)]">
                  No mistakes found in the first {report.summary.max_plies} plies.
                </div>
              ) : (
                <ul className="max-h-[280px] space-y-1.5 overflow-y-auto pr-1">
                  {repertoire.mistakes.map((mistake) => {
                    const ply = mistake.line.length + 1;
                    const isFocused =
                      focusedMistake?.fen === mistake.fen && focusedMistake.move === mistake.move;
                    return (
                      <li key={`${mistake.fen}|${mistake.move}`}>
                        <button
                          type="button"
                          onClick={() => openMistake(mistake)}
                          className={`flex w-full flex-col gap-1 rounded-md border px-3 py-2 text-left text-sm transition hover:cursor-pointer sm:flex-row sm:items-center sm:justify-between sm:gap-3 ${
                            isFocused
                              ? "border-[rgba(110,231,183,0.35)] bg-[var(--accent-muted)]"
                              : "border-white/6 bg-white/4 hover:bg-white/8"
                          }`}
                        >
                          <span className="whitespace-nowrap">
                            <span className="font-mono font-medium text-white">
                              {formatMoveNumber(ply)} {uciToSan(mistake.fen, mistake.move)}
                            </span>
                            {mistake.best_move && (
                              <span className="ml-2 text-[var(--muted)]">
                                best <span className="font-mono text-[var(--accent)]">{uciToSan(mistake.fen, mistake.best_move)}</span>
                              </span>
                            )}
                          </span>
                          <span className="flex shrink-0 items-center gap-3 whitespace-nowrap text-[var(--muted)]">
                            <span>{mistake.count}×</span>
                            <span className="font-mono">
                              {formatEval(mistake.evaluation_before)} → {formatEval(mistake.evaluation_after)}
                            </span>
                            <ClassificationChip classification={mistake.classification} />
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {repertoire.mistakes_total > repertoire.mistakes.length && (
                <div className="mt-2 text-xs text-[var(--muted)]">
                  Showing the top {repertoire.mistakes.length} of {repertoire.mistakes_total} by impact.
                </div>
              )}
            </Card>

            <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-6 text-[var(--muted)]">
              <h2 className="text-xl font-semibold text-white mb-4">Position Statistics</h2>
              {currentStats ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                    <div>Occurrences: <span className="text-white font-mono">{currentStats.occurrences}</span></div>
                    <div>Win Rate: <span className="text-white font-mono">{Math.round((currentStats.wins / currentStats.occurrences) * 100)}%</span></div>
                    <div>Draw Rate: <span className="text-white font-mono">{Math.round((currentStats.draws / currentStats.occurrences) * 100)}%</span></div>
                  </div>

                  {currentStats.player_to_move && currentStats.evaluation && (
                    <div className="text-sm">
                      Evaluation (for you):{" "}
                      <span className="text-white font-mono">{formatEval(currentStats.evaluation)}</span>
                      {currentStats.best_move && (
                        <>
                          <span className="mx-2">·</span>
                          Engine best move:{" "}
                          <span className="text-[var(--accent)] font-semibold font-mono">
                            {uciToSan(currentStats.fen, currentStats.best_move)}
                          </span>
                        </>
                      )}
                    </div>
                  )}
                  {!currentStats.player_to_move && (
                    <div className="text-sm">Your opponents' replies in this position:</div>
                  )}

                  <div>
                    <h3 className="text-sm font-semibold text-white mb-2 border-b border-white/10 pb-1">Played Moves</h3>
                    <ul className="space-y-1">
                      {Object.entries(currentStats.played_moves)
                        .sort((a, b) => b[1].count - a[1].count)
                        .map(([move, played]) => (
                        <li key={move} className="text-sm">
                          <button
                            type="button"
                            onClick={() => playMove(move)}
                            className="flex w-full items-center justify-between gap-3 rounded bg-white/5 px-2 py-1 text-left transition hover:bg-white/10 hover:cursor-pointer"
                            aria-label={`Play ${uciToSan(currentStats.fen, move)}`}
                          >
                            <span className="flex items-center gap-2">
                              <span className="font-mono text-white">{uciToSan(currentStats.fen, move)}</span>
                              {move === currentStats.best_move && (
                                <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--accent)]">best</span>
                              )}
                              {played.classification && <ClassificationChip classification={played.classification} />}
                            </span>
                            <span className="flex flex-wrap items-center justify-end gap-x-3">
                              {played.evaluation && (
                                <span className="whitespace-nowrap font-mono">
                                  {formatEval(played.evaluation)}
                                  {played.loss_cp ? ` (${formatLoss(played.loss_cp)})` : ""}
                                </span>
                              )}
                              <span className="whitespace-nowrap">{played.count} {played.count === 1 ? "time" : "times"} ({Math.round((played.count / currentStats.occurrences) * 100)}%)</span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : positionQuery.isPending ? (
                <div className="text-sm italic text-white/50">Loading position…</div>
              ) : positionQuery.isError ? (
                <div className="text-sm text-red-300">Could not load this position: {positionQuery.error.message}</div>
              ) : (
                <div className="text-sm italic text-white/50">
                  No games reached this position.
                </div>
              )}
            </Card>

            <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-white">Move list</div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPlyIndex(historyFens.length - 1)}
                  disabled={plyIndex === historyFens.length - 1}
                >
                  Jump to final position
                </Button>
              </div>
              <Separator className="mb-4 border-white/10" />
              {historySans.length > 0 ? (
                <div className="grid max-h-[160px] grid-cols-2 gap-2 overflow-y-auto pr-1 md:grid-cols-3 xl:grid-cols-4">
                  {historySans.map((san, index) => {
                    const ply = index + 1;
                    return (
                      <button
                        key={`${ply}-${san}`}
                        type="button"
                        onClick={() => setPlyIndex(ply)}
                        className={`rounded-md border px-3 py-2 text-left text-sm transition ${
                          plyIndex === ply
                            ? "border-[rgba(110,231,183,0.35)] bg-[var(--accent-muted)] text-white"
                            : "border-white/6 bg-white/4 text-[var(--muted)] hover:bg-white/8 hover:text-white"
                        }`}
                      >
                        <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--muted)]">
                          {formatMoveNumber(ply)}
                        </div>
                        <div className="mt-1 font-medium text-white">{san}</div>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="text-sm italic text-[var(--muted)]">
                  Make a move on the board, or pick a mistake above, to start exploring.
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
