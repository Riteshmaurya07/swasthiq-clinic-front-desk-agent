/**
 * Fixtures shaped exactly like the Phase 7 API responses.
 */

import { ApiError } from "@/lib/api"

export const statsFixture = { total: 6, open: 2, resolved: 4 }

export const conversationsFixture = {
  conversations: [
    { conversation_id: "cv_0011", terminal_state: "escalated" },
    { conversation_id: "cv_0007", terminal_state: "escalated" },
    { conversation_id: "cv_0009", terminal_state: "escalated" },
    { conversation_id: "cv_0010", terminal_state: "escalated" },
    { conversation_id: "cv_0001", terminal_state: "booked" },
    { conversation_id: "cv_0015", terminal_state: "booked" },
  ],
}

export const handoffsFixture = {
  handoffs: [
    {
      conversation_id: "cv_0011",
      escalation_reason: "clinical_urgent",
      caller_context: "Mujhe seena mein dard ho raha hai",
      status: "open",
      created_at: "2026-10-01T11:42:00Z",
      resolved_at: null,
    },
    {
      conversation_id: "cv_0007",
      escalation_reason: "ambiguous_patient",
      caller_context: "Sharma ji ke liye",
      status: "open",
      created_at: "2026-10-01T10:57:00Z",
      resolved_at: null,
    },
  ],
}

export const conversationFixture = {
  conversation_id: "cv_0011",
  created_at: "2026-10-01T11:42:00Z",
  today: "2026-10-01",
  turns: [
    "Mujhe kal Dr. Rao ke liye appointment chahiye",
    "Mujhe seena mein dard ho raha hai",
  ],
  transcript: [
    { seq: 0, kind: "caller", text: "Mujhe kal Dr. Rao ke liye appointment chahiye" },
    {
      seq: 1,
      kind: "tool_call",
      name: "search_slots",
      arguments: { doctor_id: "dr_rao", date: "2026-10-02" },
      result: null,
    },
    { seq: 2, kind: "caller", text: "Mujhe seena mein dard ho raha hai" },
    {
      seq: 3,
      kind: "tool_call",
      name: "escalate_to_human",
      arguments: { reason: "clinical_urgent", summary: "Caller describes symptoms needing a clinician now" },
      result: null,
    },
    {
      seq: 4,
      kind: "agent",
      text: "Main aapko team ke ek member se connect kar raha hoon.",
    },
  ],
  terminal_state: "escalated",
  escalation_reason: "clinical_urgent",
  patient_id: null,
  appointment_id: null,
  reply: "Main aapko team ke ek member se connect kar raha hoon.",
  metrics: { turns: 2, tokens: 0, latency_ms: 12 },
  tool_calls: [
    { sequence: 0, name: "search_slots", arguments: { doctor_id: "dr_rao", date: "2026-10-02" }, result: null },
    {
      sequence: 1,
      name: "escalate_to_human",
      arguments: { reason: "clinical_urgent", summary: "Caller describes symptoms needing a clinician now" },
      result: null,
    },
  ],
}


export function mockApi() {
  const calls = []
  return {
    calls,
    get(path) {
      calls.push({ path, method: "GET" })
      if (path === "/api/handoffs?status=open") return Promise.resolve(handoffsFixture)
      if (path === "/api/handoffs/stats") return Promise.resolve(statsFixture)
      if (path === "/api/conversations") return Promise.resolve(conversationsFixture)
      if (path === "/api/conversations/cv_0011") return Promise.resolve(conversationFixture)
      return Promise.reject(new Error(`unmocked path: ${path}`))
    },
    patch(path) {
      calls.push({ path, method: "PATCH" })
      if (path === "/api/handoffs/cv_0011/resolve") {
        return Promise.resolve({
          conversation_id: "cv_0011",
          status: "resolved",
          resolved_at: "2026-10-01T12:00:00Z",
        })
      }
      if (path === "/api/handoffs/cv_0007/resolve") {
        return Promise.resolve({
          conversation_id: "cv_0007",
          status: "resolved",
          resolved_at: "2026-10-01T12:00:00Z",
        })
      }
      return Promise.reject(new Error(`unmocked path: ${path}`))
    },
  }
}
