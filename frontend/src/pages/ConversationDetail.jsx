import { Link, useParams } from "react-router-dom"
import { ArrowLeft, TriangleAlert } from "lucide-react"

import { Timeline } from "@/components/conversation/Timeline"
import { OutcomePanel } from "@/components/conversation/OutcomePanel"
import { ReasonBadge } from "@/components/handoffs/ReasonBadge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError, fetchConversation } from "@/lib/api"
import { useDashboardSession } from "@/components/auth/DashboardSession"
import { useAsync } from "@/hooks/useApi"

function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6 p-6 lg:p-8">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-56" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <Card className="py-6">
          <CardContent className="flex flex-col gap-4 px-6">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="flex gap-3">
                <Skeleton className="h-4 w-16" />
                <Skeleton className={index % 2 === 0 ? "h-12 w-2/3" : "h-16 w-3/4"} />
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="py-6">
          <CardContent className="flex flex-col gap-3 px-6">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-5 w-full" />
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function NotFoundState({ conversationId }) {
  return (
    <div className="flex flex-col gap-6 p-6 lg:p-8">
      <Alert variant="destructive" data-testid="not-found-state">
        <TriangleAlert />
        <AlertTitle>Conversation not found</AlertTitle>
        <AlertDescription>
          No stored conversation matches “{conversationId}”.
        </AlertDescription>
      </Alert>
      <Button variant="outline" asChild className="w-fit">
        <Link to="/handoffs">
          <ArrowLeft data-icon="inline-start" />
          Back to Handoff Queue
        </Link>
      </Button>
    </div>
  )
}

function LoadErrorState() {
  return (
    <div className="flex flex-col gap-6 p-6 lg:p-8">
      <Alert variant="destructive" data-testid="load-error-state">
        <TriangleAlert />
        <AlertTitle>Something went wrong</AlertTitle>
        <AlertDescription>
          Could not load this conversation. Is the backend running?
        </AlertDescription>
      </Alert>
      <Button variant="outline" asChild className="w-fit">
        <Link to="/handoffs">
          <ArrowLeft data-icon="inline-start" />
          Back to Handoff Queue
        </Link>
      </Button>
    </div>
  )
}

export function ConversationDetailPage() {
  const { conversationId } = useParams()
  const { guard } = useDashboardSession()
  const { data, error, loading } = useAsync(
    () => fetchConversation(conversationId),
    [conversationId],
    guard,
  )

  if (loading) return <DetailSkeleton />
  if (error instanceof ApiError && error.status === 404) {
    return <NotFoundState conversationId={conversationId} />
  }
  if (error) return <LoadErrorState />

  const escalated = data.terminal_state === "escalated"

  return (
    <div className="flex flex-col gap-6 p-6 lg:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-tight" data-testid="detail-title">
            Conversation {data.conversation_id}
          </h1>
          <p className="text-sm text-muted-foreground">
            Sunrise Clinic, Dehradun — {data.today}
            {data.created_at ? ` · stored ${data.created_at}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {escalated && data.escalation_reason ? (
            <ReasonBadge reason={data.escalation_reason} />
          ) : null}
          <Badge
            data-testid="detail-state-badge"
            className="bg-red-100 font-semibold text-red-800 hover:bg-red-100 data-[state=non-escalated]:bg-slate-100 data-[state=non-escalated]:text-slate-700"
            data-state={escalated ? "escalated" : "non-escalated"}
          >
            {escalated ? "ESCALATED" : data.terminal_state?.toUpperCase()}
          </Badge>
        </div>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Transcript and tool calls</CardTitle>
          </CardHeader>
          <CardContent>
            <Timeline events={data.transcript} />
          </CardContent>
        </Card>
        <OutcomePanel conversation={data} />
      </div>
    </div>
  )
}
