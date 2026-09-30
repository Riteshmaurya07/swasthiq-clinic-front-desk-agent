import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { terminalStateLabel } from "@/lib/labels"

const STATE_BADGE_CLASSES = {
  booked: "bg-green-100 text-green-800 hover:bg-green-100",
  rescheduled: "bg-green-100 text-green-800 hover:bg-green-100",
  cancelled: "bg-slate-100 text-slate-700 hover:bg-slate-100",
  escalated: "bg-red-100 text-red-800 hover:bg-red-100",
  refused: "bg-orange-100 text-orange-800 hover:bg-orange-100",
  abandoned: "bg-slate-100 text-slate-700 hover:bg-slate-100",
}

function OutcomeRow({ label, value, mono = true }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span
        data-testid={`outcome-${label}`}
        className={cn("text-sm font-semibold text-right", mono && "font-mono")}
      >
        {value}
      </span>
    </div>
  )
}

function fmtMs(ms) {
  if (typeof ms !== "number") return "—"
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`
}

/**
 * Machine-readable outcome (mockup: right card). Shows the backend's actual
 * values; machine values like terminal_state appear verbatim in mono, with
 * a readable badge next to the header.
 */
export function OutcomePanel({ conversation }) {
  const { terminal_state: terminalState, escalation_reason: reason } = conversation
  const toolCount = Array.isArray(conversation.tool_calls) ? conversation.tool_calls.length : 0

  return (
    <Card data-testid="outcome-panel">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="text-lg">Outcome</CardTitle>
        <Badge data-testid="outcome-state-badge" className={cn("font-semibold", STATE_BADGE_CLASSES[terminalState])}>
          {terminalStateLabel(terminalState)}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col">
        <div className="divide-y divide-border">
          <OutcomeRow label="terminal_state" value={terminalState} />
          <OutcomeRow
            label="escalation_reason"
            value={reason ?? "null"}
          />
          <OutcomeRow label="patient_id" value={conversation.patient_id ?? "null"} />
          <OutcomeRow label="appointment_id" value={conversation.appointment_id ?? "null"} />
          <OutcomeRow label="tool_calls" value={String(toolCount)} mono={false} />
          <OutcomeRow label="turns" value={String(conversation.metrics?.turns ?? 0)} mono={false} />
          <OutcomeRow label="tokens" value={String(conversation.metrics?.tokens ?? 0)} mono={false} />
          <OutcomeRow label="latency" value={fmtMs(conversation.metrics?.latency_ms)} mono={false} />
        </div>
        <Separator className="my-4" />
        <p className="text-xs tracking-wider text-muted-foreground uppercase">Truthfulness</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Tokens are 0 because this agent is deterministic and uses no LLM.
        </p>
      </CardContent>
    </Card>
  )
}
