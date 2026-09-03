import { useState, useEffect, useMemo } from "react";
import { Chess } from "chess.js";
import { Chessboard } from "react-chessboard";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { submitReview, fetchReviewStatus, fetchReviewReports } from "@/lib/api";
import { formatMoveNumber } from "@/lib/chess";
import { useKeyboardShortcuts } from "@/components/game/use-keyboard-shortcuts";

type Bucket = {
  fen: string;
  side_to_move: "white" | "black";
  occurrences: number;
  wins: number;
  draws: number;
  played_moves: Record<string, number>;
  best_move: string | Record<string, any>;
};

export function ReviewPage() {
  const [file, setFile] = useState<File | null>(null);
  const [player, setPlayer] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [rawReports, setRawReports] = useState<any[]>([]);
  const [boardOrientation, setBoardOrientation] = useState<"white" | "black">("white");
  
  const [historyFens, setHistoryFens] = useState<string[]>([new Chess().fen()]);
  const [historySans, setHistorySans] = useState<string[]>([]);
  const [plyIndex, setPlyIndex] = useState(0);

  const decrementPly = () => setPlyIndex((value) => Math.max(0, value - 1));
  const incrementPly = () => setPlyIndex((value) => Math.min(historyFens.length - 1, value + 1));

  useKeyboardShortcuts(decrementPly, ["ArrowLeft"]);
  useKeyboardShortcuts(incrementPly, ["ArrowRight"]);

  const currentFen = historyFens[plyIndex];

  const currentNormalizedFen = useMemo(() => {
    return currentFen.split(" ").slice(0, 4).join(" ");
  }, [currentFen]);

  const aggregated = useMemo(() => {
    const agg: Record<string, Bucket> = {};
    for (const report of rawReports) {
      if (report.color !== boardOrientation) continue;
      for (const [fenKey, bucket] of Object.entries(report.buckets) as [string, Bucket][]) {
        if (!agg[fenKey]) {
          agg[fenKey] = {
            fen: bucket.fen,
            side_to_move: bucket.side_to_move,
            occurrences: 0,
            wins: 0,
            draws: 0,
            played_moves: {},
            best_move: bucket.best_move,
          };
        }
        agg[fenKey].occurrences += bucket.occurrences;
        agg[fenKey].wins += bucket.wins;
        agg[fenKey].draws += bucket.draws;
        for (const [move, count] of Object.entries(bucket.played_moves)) {
          agg[fenKey].played_moves[move] = (agg[fenKey].played_moves[move] || 0) + (count as number);
        }
        if (!agg[fenKey].best_move && bucket.best_move && Object.keys(bucket.best_move).length > 0) {
          agg[fenKey].best_move = bucket.best_move;
        }
      }
    }
    return agg;
  }, [rawReports, boardOrientation]);

  const currentStats = aggregated[currentNormalizedFen];

  useEffect(() => {
    if (!jobId || status === "completed" || status === "failed" || status === "error") return;

    const interval = setInterval(async () => {
      try {
        const res = await fetchReviewStatus(jobId);
        setStatus(res.status);
        if (res.status === "completed") {
          const reportRes = await fetchReviewReports(jobId);
          setRawReports(reportRes.reports);
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
      setStatus("uploading...");
      const res = await submitReview(file, player);
      setJobId(res.job_id);
      setStatus(res.status);
    } catch (err) {
      console.error(err);
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

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-3xl font-semibold text-white">Opening Review</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Upload your PGN to build an opening tree and review your lines.
        </p>
      </div>

      {!jobId || status === "error" ? (
        <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-6">
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
      ) : status !== "completed" ? (
        <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-6">
          <div className="text-sm text-white">Job Status: <span className="font-semibold text-[var(--accent)]">{status}</span></div>
        </Card>
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row">
          <div className="w-full max-w-[480px] shrink-0 space-y-4">
            <Chessboard 
              position={currentFen} 
              onPieceDrop={onDrop} 
              boardOrientation={boardOrientation}
              customDarkSquareStyle={{ backgroundColor: "#3f4a56" }}
              customLightSquareStyle={{ backgroundColor: "#e0e3e6" }}
              customArrows={
                typeof currentStats?.best_move === "string" && currentStats.best_move
                  ? [
                      [
                        currentStats.best_move.substring(0, 2),
                        currentStats.best_move.substring(2, 4),
                        "rgba(110, 231, 183, 0.75)"
                      ] as any
                    ]
                  : []
              }
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
              <div className="flex gap-2">
                <button 
                  onClick={() => setBoardOrientation(boardOrientation === "white" ? "black" : "white")}
                  className="rounded-md border border-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/5 transition"
                >
                  Flip Board
                </button>
                <button 
                  onClick={resetBoard}
                  className="rounded-md border border-white/10 px-3 py-1.5 text-sm text-white hover:bg-white/5 transition"
                >
                  Reset
                </button>
              </div>
            </div>
          </div>
          
          <div className="flex flex-1 flex-col gap-6">
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
                  Make a move on the board to start exploring.
                </div>
              )}
            </Card>

            <Card className="rounded-xl border border-white/10 bg-[rgba(16,22,29,0.72)] p-6 text-[var(--muted)]">
              <h2 className="text-xl font-semibold text-white mb-4">Position Statistics</h2>
              {currentStats ? (
                <div className="space-y-4">
                  <div className="flex gap-6 text-sm">
                    <div>Occurrences: <span className="text-white font-mono">{currentStats.occurrences}</span></div>
                    <div>Win Rate: <span className="text-white font-mono">{Math.round((currentStats.wins / currentStats.occurrences) * 100)}%</span></div>
                    <div>Draw Rate: <span className="text-white font-mono">{Math.round((currentStats.draws / currentStats.occurrences) * 100)}%</span></div>
                  </div>
                  
                  {typeof currentStats.best_move === "string" && currentStats.best_move && (
                    <div className="text-sm">
                      Engine Best Move: <span className="text-[var(--accent)] font-semibold font-mono ml-2">{currentStats.best_move}</span>
                    </div>
                  )}

                  <div>
                    <h3 className="text-sm font-semibold text-white mb-2 border-b border-white/10 pb-1">Played Moves</h3>
                    <ul className="space-y-1">
                      {Object.entries(currentStats.played_moves)
                        .sort((a, b) => b[1] - a[1])
                        .map(([move, count]) => (
                        <li key={move} className="text-sm">
                          <button
                            type="button"
                            onClick={() => playMove(move)}
                            className="flex w-full justify-between rounded bg-white/5 px-2 py-1 text-left transition hover:bg-white/10 hover:cursor-pointer"
                            aria-label={`Play ${move}`}
                          >
                            <span className="font-mono text-white">{move}</span>
                            <span>{count} times ({Math.round((count / currentStats.occurrences) * 100)}%)</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ) : (
                <div className="text-sm italic text-white/50">
                  No games reached this position.
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
