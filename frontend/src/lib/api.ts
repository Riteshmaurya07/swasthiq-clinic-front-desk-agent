/**
 * Central API layer for the dashboard.
 *
 * - Base URL comes from VITE_API_BASE_URL (empty = same origin, which the
 *   Vite dev server proxies to the backend).
 * - Every failure is normalized to an ApiError so components never parse
 *   raw responses or leak stack traces.
 * - Dashboard routes are session-protected (H-2). The session lives in an
 *   HttpOnly cookie the browser manages, so every request opts in with
 *   `credentials: "include"` and no token is ever held in JS.
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

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      // Required for the HttpOnly session cookie to travel with dashboard calls.
      credentials: "include",
    })
  } catch {
    throw new ApiError("Cannot reach the clinic server. Is the backend running?", 0)
  }
  if (!response.ok) {
    if (response.status === 401) {
      throw new ApiError("Your dashboard session has ended. Please sign in again.", 401)
    }
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

// ------------------------------------------------------------------- auth
//
// H-2: the dashboard APIs above are session-protected. The password is sent
// once to the login endpoint and is never persisted anywhere in the browser —
// no localStorage, no sessionStorage, no hardcoded default. The resulting
// session is an HttpOnly cookie the browser stores and replays on its own.

/**
 * Authentication state only.
 *
 * The server never returns the configured username, so the dashboard UI cannot
 * display or leak it — a session is treated as an anonymous bearer capability.
 */
export interface DashboardSession {
  authenticated: boolean
}

export function login(username: string, password: string): Promise<DashboardSession> {
  return request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
}

export function logout(): Promise<DashboardSession> {
  return request("/api/auth/logout", { method: "POST" })
}

/** Rejects with an ApiError(401) when there is no valid session. */
export function fetchSession(): Promise<DashboardSession> {
  return request("/api/auth/me")
}
