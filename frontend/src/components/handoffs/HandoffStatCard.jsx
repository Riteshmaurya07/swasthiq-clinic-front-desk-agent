import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/**
 * One counter card (mockup: small uppercase label, large number, sub-note).
 * Values come straight from GET /api/handoffs/stats — never invented.
 */
export function HandoffStatCard({ label, value, note, noteClass }) {
  return (
    <Card data-testid="stat-card" className="py-5">
      <CardContent className="flex flex-col gap-1 px-5">
        <span className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
          {label}
        </span>
        <span className="text-3xl font-bold tabular-nums">{value}</span>
        {note ? (
          <span className={cn("text-sm", noteClass ?? "text-muted-foreground")}>{note}</span>
        ) : null}
      </CardContent>
    </Card>
  )
}
