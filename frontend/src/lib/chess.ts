import { Chess } from "chess.js";

export type ParsedMove = {
  uci: string;
  san: string;
  fen: string;
  ply: number;
};

function toMoveObject(uci: string) {
  return {
    from: uci.slice(0, 2),
    to: uci.slice(2, 4),
    promotion: uci.length > 4 ? uci[4] : undefined,
  };
}

export function parseUciMoves(pgnMoves?: string | null) {
  const chess = new Chess();
  const moves = (pgnMoves || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  const parsed: ParsedMove[] = [];

  for (const [index, uci] of moves.entries()) {
    const result = chess.move(toMoveObject(uci));
    if (!result) {
      break;
    }
    parsed.push({
      uci,
      san: result.san,
      fen: chess.fen(),
      ply: index + 1,
    });
  }

  return {
    initialFen: new Chess().fen(),
    moves: parsed,
  };
}

export function formatMoveNumber(ply: number) {
  const moveNumber = Math.ceil(ply / 2);
  return ply % 2 === 1 ? `${moveNumber}.` : `${moveNumber}...`;
}
