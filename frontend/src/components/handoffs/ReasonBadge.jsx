import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { escalationBadgeVariant, escalationLabel } from "@/lib/labels"

const VARIANT_CLASSES = {
  clinical: "bg-red-50 text-red-700 hover:bg-red-50",
  warning: "bg-amber-50 text-amber-700 hover:bg-amber-50",
  amber: "bg-yellow-50 text-yellow-700 hover:bg-yellow-50",
}

/** Escalation reason badge — readable label, machine value preserved via title. */
export function ReasonBadge({ reason }) {
  const variant = escalationBadgeVariant(reason)
  return (
    <Badge
      variant="secondary"
      data-testid="reason-badge"
      title={reason}
      className={cn("font-semibold tracking-wide uppercase", VARIANT_CLASSES[variant])}
    >
      {escalationLabel(reason)}
    </Badge>
  )
}
