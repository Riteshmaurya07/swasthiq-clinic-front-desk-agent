import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatTime } from "@/lib/labels"
import { ReasonBadge } from "@/components/handoffs/ReasonBadge"

function HandoffTableHeader() {
  return (
    <TableHeader>
      <TableRow>
        <TableHead className="w-[14%]">Conversation</TableHead>
        <TableHead className="w-[46%]">Caller said</TableHead>
        <TableHead className="w-[18%]">Reason</TableHead>
        <TableHead className="w-[10%]">Time</TableHead>
        <TableHead className="w-[12%] text-right">Action</TableHead>
      </TableRow>
    </TableHeader>
  )
}

export { HandoffTableHeader }

/** One open handoff (mockup row: id, caller statement, reason badge, time, Resolve). */
export function HandoffRow({ handoff, onResolve, resolving }) {
  return (
    <TableRow data-testid="handoff-row" data-conversation-id={handoff.conversation_id}>
      <TableCell>
        <Link
          to={`/conversations/${encodeURIComponent(handoff.conversation_id)}`}
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          {handoff.conversation_id}
        </Link>
      </TableCell>
      <TableCell className="max-w-0">
        <p className="truncate font-medium" title={handoff.caller_context}>
          {handoff.caller_context}
        </p>
      </TableCell>
      <TableCell>
        <ReasonBadge reason={handoff.escalation_reason} />
      </TableCell>
      <TableCell className="tabular-nums text-muted-foreground">
        {formatTime(handoff.created_at)}
      </TableCell>
      <TableCell className="text-right">
        <Button
          size="sm"
          variant={resolving ? "default" : "outline"}
          disabled={resolving}
          aria-label={`Resolve handoff ${handoff.conversation_id}`}
          data-testid={`resolve-${handoff.conversation_id}`}
          onClick={() => onResolve(handoff.conversation_id)}
        >
          {resolving ? <Spinner data-icon="inline-start" /> : null}
          Resolve
        </Button>
      </TableCell>
    </TableRow>
  )
}
