import { Chess } from "chess.js";

export type ParsedMove = {
  uci: string;
  san: string;
  fen: string;
  ply: number;
};

export function toMoveObject(uci: string) {
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

export function uciToSan(fen: string, uci: string) {
  try {
    return new Chess(fen).move(toMoveObject(uci)).san;
  } catch {
    return uci;
  }
}

// Formats an engine score: +0.4, -1.2, M3, -M2, or # when the move delivers checkmate
export function formatEval(score: { cp: number | null; mate: number | null } | null | undefined) {
  if (!score) return "";
  if (score.mate !== null) {
    if (score.mate === 0) return "#";
    return score.mate > 0 ? `M${score.mate}` : `-M${-score.mate}`;
  }
  if (score.cp === null) return "";
  const pawns = score.cp / 100;
  return `${pawns > 0 ? "+" : ""}${pawns.toFixed(1)}`;
}

// Position key used by the review tree: FEN without the move clocks
export function normalizeFen(fen: string) {
  return fen.split(" ").slice(0, 4).join(" ");
}

// Normalized FENs reached from `fen` by each of the given UCI moves
export function childFens(fen: string, ucis: string[]) {
  const fens: string[] = [];
  for (const uci of ucis) {
    try {
      const chess = new Chess(fen);
      chess.move(toMoveObject(uci));
      fens.push(normalizeFen(chess.fen()));
    } catch {
      // skip moves that are illegal in this position
    }
  }
  return fens;
}

// Normalized FENs of every position along a line from the start position, including the final one
export function lineFens(line: string[]) {
  const chess = new Chess();
  const fens = [normalizeFen(chess.fen())];
  for (const uci of line) {
    try {
      chess.move(toMoveObject(uci));
    } catch {
      break;
    }
    fens.push(normalizeFen(chess.fen()));
  }
  return fens;
}
