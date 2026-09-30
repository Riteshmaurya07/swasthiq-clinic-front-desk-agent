import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { ToolCallCard } from "@/components/conversation/ToolCallCard"

function RoleLabel({ children }) {
  return (
    <span className="w-16 shrink-0 pt-2 text-right text-xs font-medium tracking-wider text-muted-foreground uppercase">
      {children}
    </span>
  )
}

function CallerMessage({ text }) {
  return (
    <div className="flex gap-3" data-testid="caller-message">
      <RoleLabel>Caller</RoleLabel>
      <div className="inline-block max-w-2xl rounded-md rounded-tl-none bg-muted px-3.5 py-2.5">
        <p className="text-sm whitespace-pre-wrap">{text}</p>
      </div>
    </div>
  )
}

function AgentMessage({ text }) {
  return (
    <div className="flex gap-3" data-testid="agent-message">
      <RoleLabel>Agent</RoleLabel>
      <div className="inline-block max-w-2xl rounded-md border bg-card px-3.5 py-2.5">
        <p className="text-sm whitespace-pre-wrap">{text}</p>
      </div>
    </div>
  )
}

/**
 * Ordered transcript: caller turns, tool calls exactly where they fired
 * (persisted seq order — never reconstructed from timestamps), and the
 * final agent reply. Unknown event kinds are skipped, not fabricated.
 */
export function Timeline({ events }) {
  return (
    <div className="flex flex-col gap-3" data-testid="timeline">
      {events.map((event) => {
        if (event.kind === "caller") {
          return <CallerMessage key={event.seq} text={event.text ?? ""} />
        }
        if (event.kind === "tool_call") {
          return (
            <div key={event.seq} className="flex gap-3">
              <RoleLabel>Tool</RoleLabel>
              <div className="min-w-0 flex-1">
                <ToolCallCard
                  toolCall={{ name: event.name, arguments: event.arguments, sequence: event.seq }}
                />
              </div>
            </div>
          )
        }
        if (event.kind === "agent") {
          return <AgentMessage key={event.seq} text={event.text ?? ""} />
        }
        return null
      })}
    </div>
  )
}

export { Separator, cn }
