import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import { ApiError } from "@/lib/api"
import { handoffsFixture, mockApi, mockSession } from "./fixtures"

let api
let session

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    fetchConversation: vi.fn((id) => api.get(`/api/conversations/${id}`)),
    fetchHandoffs: vi.fn(() => Promise.resolve(handoffsFixture)),
    fetchHandoffStats: vi.fn(() => Promise.resolve({ total: 0, open: 0, resolved: 0 })),
    // H-2: the dashboard is session-gated, so the app checks /api/auth/me first.
    fetchSession: vi.fn(() => session.me()),
    login: vi.fn((u, p) => session.login(u, p)),
    logout: vi.fn(() => session.logout()),
  }
})

beforeEach(() => {
  api = mockApi()
  session = mockSession()
  session.signIn() // these tests describe the post-login dashboard
  vi.clearAllMocks()
})

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe("conversation detail", () => {
  it("loads and shows the conversation header", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() =>
      expect(screen.getByTestId("detail-title")).toHaveTextContent("Conversation cv_0011"),
    )
  })

  it("renders the transcript caller and agent events", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getByTestId("timeline")).toBeInTheDocument())
    expect(screen.getByText("Mujhe kal Dr. Rao ke liye appointment chahiye")).toBeInTheDocument()
    expect(
      screen.getByText("Main aapko team ke ek member se connect kar raha hoon."),
    ).toBeInTheDocument()
  })

  it("renders every tool call inline with its name and arguments", async () => {
    renderAt("/conversations/cv_0011")
    const cards = await screen.findAllByTestId("tool-call-card")
    expect(cards).toHaveLength(2)
    expect(screen.getAllByText(/search_slots/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/escalate_to_human/).length).toBeGreaterThan(0)
    // arguments rendered in the signature line
    expect(screen.getAllByText(/doctor_id="dr_rao"/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/reason="clinical_urgent"/).length).toBeGreaterThan(0)
  })

  it("preserves the persisted tool-call order", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getByTestId("timeline")).toBeInTheDocument())
    const timeline = screen.getByTestId("timeline")
    const texts = Array.from(timeline.querySelectorAll("[data-testid='tool-call-card'] code")).map(
      (node) => node.textContent,
    )
    expect(texts.some((t) => t.startsWith("search_slots"))).toBe(true)
    expect(texts.some((t) => t.startsWith("escalate_to_human"))).toBe(true)
    expect(texts.findIndex((t) => t.startsWith("search_slots"))).toBeLessThan(
      texts.findIndex((t) => t.startsWith("escalate_to_human")),
    )
  })

  it("shows the machine-readable outcome panel", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getByTestId("outcome-panel")).toBeInTheDocument())
    expect(screen.getByTestId("outcome-terminal_state")).toHaveTextContent("escalated")
    expect(screen.getByTestId("outcome-escalation_reason")).toHaveTextContent("clinical_urgent")
    expect(screen.getByTestId("outcome-patient_id")).toHaveTextContent("null")
    expect(screen.getByTestId("outcome-tool_calls")).toHaveTextContent("2")
  })

  it("surfaces the escalation reason in the header", async () => {
    renderAt("/conversations/cv_0011")
    const badge = await screen.findByTestId("detail-state-badge")
    expect(badge).toHaveTextContent("ESCALATED")
    const reasonBadge = screen.getByTestId("reason-badge")
    expect(reasonBadge).toHaveAttribute("title", "clinical_urgent")
  })

  it("renders truthful metrics including zero tokens with the honest label", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getByTestId("outcome-tokens")).toBeInTheDocument())
    expect(screen.getByTestId("outcome-tokens")).toHaveTextContent("0")
    expect(screen.getByTestId("outcome-turns")).toHaveTextContent("2")
    expect(screen.getByTestId("outcome-latency")).toHaveTextContent("12 ms")
    expect(screen.getByText(/deterministic and uses no LLM/i)).toBeInTheDocument()
  })

  it("omits fake values for null ids (renders literal null)", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getByTestId("outcome-appointment_id")).toBeInTheDocument())
    expect(screen.getByTestId("outcome-appointment_id")).toHaveTextContent("null")
  })

  it("shows a 404 state for an unknown conversation", async () => {
    api.get = () => Promise.reject(new ApiError("Not found", 404))
    renderAt("/conversations/nope")
    await waitFor(() => expect(screen.getByTestId("not-found-state")).toBeInTheDocument())
  })

  it("shows an error state when the API is unavailable", async () => {
    api.get = () => Promise.reject(new ApiError("Cannot reach the clinic server. Is the backend running?", 0))
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getByTestId("load-error-state")).toBeInTheDocument())
  })

  it("does not render a fabricated tool result section", async () => {
    renderAt("/conversations/cv_0011")
    await waitFor(() => expect(screen.getAllByTestId("tool-call-card").length).toBe(2))
    // No "Result" heading exists anywhere: results are not persisted.
    expect(screen.queryByText(/^result$/i)).not.toBeInTheDocument()
  })
})

describe("navigation", () => {
  it("navigates from the queue to conversation detail via the id link", async () => {
    const user = (await import("@testing-library/user-event")).default.setup()
    renderAt("/handoffs")
    const link = await screen.findByRole("link", { name: "cv_0011" })
    await user.click(link)
    await waitFor(() =>
      expect(screen.getByTestId("detail-title")).toHaveTextContent("Conversation cv_0011"),
    )
  })
})
