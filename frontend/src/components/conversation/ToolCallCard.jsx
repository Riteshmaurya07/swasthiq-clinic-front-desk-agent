import { useState } from "react"
import { ChevronDown, ChevronRight, Wrench } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"

function formatArguments(args) {
  const entries = Object.entries(args ?? {})
  if (entries.length === 0) return "()"
  const parts = entries.map(([key, value]) => {
    const rendered = typeof value === "string" ? JSON.stringify(value) : JSON.stringify(value) ?? "null"
    return `${key}=${rendered}`
  })
  return parts.join(", ")
}

/**
 * Inline tool-call block (mockup: blue left border, mono signature line).
 * Shows ONLY persisted data: name + arguments. Per-tool results are not
 * persisted by the backend, so none are rendered.
 */
export function ToolCallCard({ toolCall }) {
  const [open, setOpen] = useState(false)
  const hasArguments = Object.keys(toolCall.arguments ?? {}).length > 0

  return (
    <Collapsible open={open} onOpenChange={setOpen} data-testid="tool-call-card">
      <div className="overflow-hidden rounded-md border border-border border-l-4 border-l-blue-600 bg-blue-50/50">
        <CollapsibleTrigger
          className="flex w-full items-start gap-2 px-3 py-2.5 text-left"
          aria-label={`Tool call ${toolCall.name}, arguments ${formatArguments(toolCall.arguments)}`}
        >
          {hasArguments ? (
            open ? (
              <ChevronDown className="mt-0.5 size-4 shrink-0 text-blue-700" />
            ) : (
              <ChevronRight className="mt-0.5 size-4 shrink-0 text-blue-700" />
            )
          ) : (
            <Wrench className="mt-0.5 size-4 shrink-0 text-blue-700" />
          )}
          <code className="min-w-0 flex-1 text-sm break-words text-blue-900">
            <span className="font-bold">{toolCall.name}</span>(
            <span className="break-all">{formatArguments(toolCall.arguments)}</span>)
          </code>
          {typeof toolCall.sequence === "number" ? (
            <Badge variant="outline" className="shrink-0 tabular-nums">
              #{toolCall.sequence}
            </Badge>
          ) : null}
        </CollapsibleTrigger>
        {hasArguments ? (
          <CollapsibleContent>
            <pre
              data-testid="tool-call-arguments"
              className="overflow-x-auto border-t border-blue-100 px-3 py-2 text-xs text-blue-950"
            >
              {JSON.stringify(toolCall.arguments, null, 2)}
            </pre>
          </CollapsibleContent>
        ) : null}
      </div>
    </Collapsible>
  )
}
