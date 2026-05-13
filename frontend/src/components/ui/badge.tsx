import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-medium uppercase tracking-[0.12em]",
  {
    variants: {
      variant: {
        default:
          "border-[var(--panel-border)] bg-white/5 text-[var(--muted)]",
        accent:
          "border-[rgba(110,231,183,0.25)] bg-[var(--accent-muted)] text-[var(--accent)]",
        warm: "border-[rgba(251,191,36,0.22)] bg-[rgba(251,191,36,0.12)] text-[var(--warning)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

interface BadgeProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
