import { Card } from "@/components/ui/card";

export function ReviewPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-3xl font-semibold text-white">Review</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          This page is reserved for PGN upload and analysis. The search and game
          detail MVP is wired first, and review can slot into this route next.
        </p>
      </div>

      <Card className="rounded-xl border border-dashed border-white/10 bg-[rgba(16,22,29,0.72)] p-6 text-sm text-[var(--muted)]">
        Upload, server-side analysis, and board annotations are not connected yet.
      </Card>
    </div>
  );
}
