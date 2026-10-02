/**
 * Central API layer for the dashboard.
 *
 * - Base URL comes from VITE_API_BASE_URL (empty = same origin, which the
 *   Vite dev server proxies to the backend).
 * - Every failure is normalized to an ApiError so components never parse
 *   raw responses or leak stack traces.
 */

const BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "")

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}



async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
    })
  } catch {
    throw new ApiError("Cannot reach the clinic server. Is the backend running?", 0)
  }
  if (!response.ok) {
    if (response.status === 404) {
      throw new ApiError("Not found", 404)
    }
    throw new ApiError(
      `Request failed (HTTP ${response.status})`,
      response.status,
    )
  }
  return response.json() as Promise<T>
}

// ---------------------------------------------------------------- types

export interface Handoff {
  conversation_id: string
  escalation_reason: string
  caller_context: string
  status: "open" | "resolved"
  created_at: string
  resolved_at: string | null
}

export interface HandoffStats {
  total: number
  open: number
  resolved: number
}

export interface TimelineEvent {
  seq: number
  kind: "caller" | "tool_call" | "agent"
  text?: string
  name?: string
  arguments?: Record<string, unknown>
  result?: Record<string, unknown> | null
}

export interface ToolCall {
  sequence: number
  name: string
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
}

export interface ConversationDetail {
  conversation_id: string
  created_at: string | null
  today: string
  turns: string[]
  transcript: TimelineEvent[]
  terminal_state: string
  escalation_reason: string | null
  patient_id: string | null
  appointment_id: string | null
  reply: string
  metrics: { turns: number; tokens: number; latency_ms: number }
  tool_calls: ToolCall[]
}

// ---------------------------------------------------------------- endpoints

export function fetchHandoffs(status?: "open" | "resolved"): Promise<{ handoffs: Handoff[] }> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ""
  return request(`/api/handoffs${query}`)
}

export function fetchHandoffStats(): Promise<HandoffStats> {
  return request("/api/handoffs/stats")
}

export function fetchConversations(): Promise<{ conversations: { conversation_id: string; terminal_state: string }[] }> {
  return request("/api/conversations")
}

export function resolveHandoff(conversationId: string): Promise<{ conversation_id: string; status: string; resolved_at: string | null }> {
  return request(`/api/handoffs/${encodeURIComponent(conversationId)}/resolve`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  })
}

export function fetchConversation(conversationId: string): Promise<ConversationDetail> {
  return request(`/api/conversations/${encodeURIComponent(conversationId)}`)
}
