import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatResult(result?: string | null) {
  if (result === "1-0") return "White won";
  if (result === "0-1") return "Black won";
  if (result === "1/2-1/2") return "Draw";
  return "Unknown result";
}

export function formatDate(date?: string | null) {
  if (!date) return "Unknown date";
  return date.replaceAll(".", "-");
}

export function formatElo(value?: number | null) {
  return value ? `${value}` : "Unrated";
}

export function titleCaseEndgame(value?: string | null) {
  if (!value || value === "none") return null;
  return value
    .split("_")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}
