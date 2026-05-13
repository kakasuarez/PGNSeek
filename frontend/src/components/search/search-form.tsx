import { Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SearchForm({
  initialValue,
  onSubmit,
}: {
  initialValue: string;
  onSubmit: (value: string) => void;
}) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(value.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="flex w-full items-center gap-3 rounded-2xl border border-white/8 bg-[rgba(16,22,29,0.92)] p-2 shadow-[0_24px_80px_rgba(0,0,0,0.35)]">
        <div className="flex flex-1 items-center gap-3 rounded-xl border border-transparent bg-[var(--panel)] px-3">
          <Search className="h-4 w-4 text-[var(--muted)]" />
          <Input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Search openings, players, style, result, rating..."
            className="border-0 bg-transparent px-0 shadow-none focus:border-0"
          />
        </div>
        <Button type="submit" className="rounded-xl px-5">
          Search
        </Button>
      </div>
    </form>
  );
}
