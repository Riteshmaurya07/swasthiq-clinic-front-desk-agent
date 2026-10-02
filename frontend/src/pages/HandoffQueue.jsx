import { useMemo, useState } from "react"

import { HandoffStatCard } from "@/components/handoffs/HandoffStatCard"
import { HandoffRow, HandoffTableHeader } from "@/components/handoffs/HandoffRow"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table"
import { ApiError, fetchConversations, fetchHandoffStats, fetchHandoffs, resolveHandoff } from "@/lib/api"
import { useDashboardSession } from "@/components/auth/DashboardSession"
import { useAsync } from "@/hooks/useApi"
import { CircleCheckBig, TriangleAlert } from "lucide-react"

const TABLE_SKELETON_ROWS = 4

function StatsSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((index) => (
        <Card key={index} className="py-5">
          <CardContent className="flex flex-col gap-2 px-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-9 w-12" />
            <Skeleton className="h-4 w-20" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function TableSkeleton() {
  return (
    <Table>
      <HandoffTableHeader />
      <TableBody>
        {Array.from({ length: TABLE_SKELETON_ROWS }).map((_, index) => (
          <TableRow key={index}>
            <TableCell><Skeleton className="h-4 w-16" /></TableCell>
            <TableCell><Skeleton className="h-4 w-full max-w-sm" /></TableCell>
            <TableCell><Skeleton className="h-6 w-28" /></TableCell>
            <TableCell><Skeleton className="h-4 w-12" /></TableCell>
            <TableCell className="text-right"><Skeleton className="ml-auto h-8 w-20" /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function ErrorState({ error }) {
  const message =
    error instanceof ApiError && error.status === 0
      ? error.message
      : "Could not load the handoff queue. Please try again."
  return (
    <Alert variant="destructive" data-testid="error-state">
      <TriangleAlert />
      <AlertTitle>Something went wrong</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  )
}

const COMPLETED_STATES = new Set(["booked", "rescheduled", "cancelled"])

/**
 * The four counter cards (mockup). Every value is derived from real API
 * responses — handoff stats for open/escalated, the stored conversation
 * list for totals and agent completions. Nothing invented.
 */
function StatsGrid({ conversationCount, conversationStates, stats, openHandoffs }) {
  const completed = conversationStates.filter((s) => COMPLETED_STATES.has(s)).length
  const escalated = conversationStates.filter((s) => s === "escalated").length
  const pct = conversationCount > 0 ? Math.round((completed / conversationCount) * 100) : 0
  const urgent = openHandoffs.filter((h) => h.escalation_reason === "clinical_urgent").length

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="stats-grid">
      <HandoffStatCard label="Conversations" value={conversationCount} note="stored" />
      <HandoffStatCard
        label="Completed by agent"
        value={completed}
        note={`${pct}% of conversations`}
      />
      <HandoffStatCard
        label="Escalated"
        value={escalated || stats.total}
        note={`${stats.open} still open`}
        noteClass="text-blue-600"
      />
      <HandoffStatCard
        label="Urgent"
        value={urgent}
        note={urgent > 0 ? "clinical, unresolved" : "none unresolved"}
        noteClass={urgent > 0 ? "text-red-600" : "text-muted-foreground"}
      />
    </div>
  )
}

function EmptyQueue() {
  return (
    <Empty data-testid="empty-state" className="border border-dashed">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <CircleCheckBig />
        </EmptyMedia>
        <EmptyTitle>Queue is clear</EmptyTitle>
        <EmptyDescription>
          There are currently no open handoffs. Conversations the agent escalates will appear here.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

export function HandoffQueuePage() {
  const [resolvingId, setResolvingId] = useState(null)
  const [resolveError, setResolveError] = useState(null)
  // A 401 anywhere below means the session ended: hand it back to the provider
  // so the operator lands on the sign-in screen instead of a dead queue.
  const { guard } = useDashboardSession()
  const handoffs = useAsync(() => fetchHandoffs("open"), [], guard)
  const stats = useAsync(() => fetchHandoffStats(), [], guard)
  const conversations = useAsync(() => fetchConversations(), [], guard)

  const openCount = useMemo(
    () => handoffs.data?.handoffs.length ?? stats.data?.open ?? 0,
    [handoffs.data, stats.data],
  )

  async function handleResolve(conversationId) {
    if (resolvingId) return // prevent duplicate submissions
    setResolvingId(conversationId)
    setResolveError(null)
    try {
      const result = await resolveHandoff(conversationId)
      if (result.status !== "resolved") {
        throw new ApiError("Unexpected resolution state", 500)
      }
      await Promise.all([handoffs.refetch(), stats.refetch(), conversations.refetch()])
    } catch (error) {
      guard(error)
      setResolveError(
        error instanceof ApiError && error.status === 404
          ? "This handoff no longer exists. The list has been refreshed."
          : "Could not resolve this handoff. Please try again.",
      )
      await handoffs.refetch().catch(() => {})
    } finally {
      setResolvingId(null)
    }
  }

  return (
    <div className="flex flex-col gap-6 p-6 lg:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight">Handoff Queue</h1>
          <p className="text-sm text-muted-foreground">
            Sunrise Clinic, Dehradun — conversations the agent escalated
          </p>
        </div>
        <Badge
          data-testid="open-count-badge"
          className="bg-blue-600 text-white hover:bg-blue-600"
        >
          {openCount} OPEN
        </Badge>
      </header>

      {stats.loading || conversations.loading ? (
        <StatsSkeleton />
      ) : stats.error || conversations.error ? (
        <ErrorState error={stats.error ?? conversations.error} />
      ) : (
        <StatsGrid
          conversationCount={conversations.data.conversations.length}
          conversationStates={conversations.data.conversations.map((c) => c.terminal_state)}
          stats={stats.data}
          openHandoffs={handoffs.data?.handoffs ?? []}
        />
      )}

      {resolveError ? (
        <Alert variant="destructive" data-testid="resolve-error">
          <TriangleAlert />
          <AlertTitle>Resolve failed</AlertTitle>
          <AlertDescription>{resolveError}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Open handoffs</CardTitle>
        </CardHeader>
        <CardContent>
          {handoffs.loading ? (
            <TableSkeleton />
          ) : handoffs.error ? (
            <ErrorState error={handoffs.error} />
          ) : handoffs.data.handoffs.length === 0 ? (
            <EmptyQueue />
          ) : (
            <Table>
              <HandoffTableHeader />
              <TableBody>
                {handoffs.data.handoffs.map((handoff) => (
                  <HandoffRow
                    key={handoff.conversation_id}
                    handoff={handoff}
                    onResolve={handleResolve}
                    resolving={resolvingId === handoff.conversation_id}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
