import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { Chessboard } from "react-chessboard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { parseUciMoves, formatMoveNumber } from "@/lib/chess";

export function BoardViewer({ pgnMoves }: { pgnMoves?: string | null }) {
  const parsed = useMemo(() => parseUciMoves(pgnMoves), [pgnMoves]);
  const [plyIndex, setPlyIndex] = useState(parsed.moves.length);

  const currentFen =
    plyIndex === 0 ? parsed.initialFen : parsed.moves[plyIndex - 1]?.fen;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <Card className="rounded-xl border-white/8 bg-[rgba(16,22,29,0.92)] p-4">
        <div className="mx-auto w-full max-w-[420px]">
          <Chessboard
            id="game-board"
            arePiecesDraggable={false}
            position={currentFen}
            customDarkSquareStyle={{ backgroundColor: "#315443" }}
            customLightSquareStyle={{ backgroundColor: "#d7e3d0" }}
            customBoardStyle={{
              borderRadius: "12px",
              overflow: "hidden",
              boxShadow: "0 24px 60px rgba(0,0,0,0.35)",
            }}
          />
        </div>

        <div className="mt-4 flex items-center justify-between gap-3">
          <Button
            variant="secondary"
            size="icon"
            onClick={() => setPlyIndex((value) => Math.max(0, value - 1))}
            disabled={plyIndex === 0}
            aria-label="Previous move"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="text-sm text-[var(--muted)]">
            Move {plyIndex} of {parsed.moves.length}
          </div>
          <Button
            variant="secondary"
            size="icon"
            onClick={() =>
              setPlyIndex((value) => Math.min(parsed.moves.length, value + 1))
            }
            disabled={plyIndex === parsed.moves.length}
            aria-label="Next move"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </Card>

      <Card className="rounded-xl border-white/8 bg-[rgba(16,22,29,0.92)] p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-sm font-semibold text-white">Move list</div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPlyIndex(parsed.moves.length)}
          >
            Jump to final position
          </Button>
        </div>
        <Separator className="mb-4" />
        <div className="grid max-h-[540px] grid-cols-2 gap-2 overflow-y-auto pr-1 md:grid-cols-3 xl:grid-cols-4">
          {parsed.moves.map((move) => (
            <button
              key={`${move.ply}-${move.uci}`}
              type="button"
              onClick={() => setPlyIndex(move.ply)}
              className={`rounded-md border px-3 py-2 text-left text-sm transition ${
                plyIndex === move.ply
                  ? "border-[rgba(110,231,183,0.35)] bg-[var(--accent-muted)] text-white"
                  : "border-white/6 bg-white/4 text-[var(--muted)] hover:bg-white/8 hover:text-white"
              }`}
            >
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--muted)]">
                {formatMoveNumber(move.ply)}
              </div>
              <div className="mt-1 font-medium text-white">{move.san}</div>
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}
