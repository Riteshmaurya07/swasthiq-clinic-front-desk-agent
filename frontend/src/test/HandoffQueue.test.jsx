import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import { ApiError } from "@/lib/api"
import { conversationsFixture, handoffsFixture, mockApi, statsFixture } from "./fixtures"

let api

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    fetchHandoffs: vi.fn((...args) => api.get("/api/handoffs?status=open", ...args)),
    fetchHandoffStats: vi.fn(() => api.get("/api/handoffs/stats")),
    fetchConversations: vi.fn(() => api.get("/api/conversations")),
    resolveHandoff: vi.fn((id) => api.patch(`/api/handoffs/${id}/resolve`)),
  }
})

beforeEach(() => {
  api = mockApi()
  vi.clearAllMocks()
})

function renderQueue() {
  return render(
    <MemoryRouter initialEntries={["/handoffs"]}>
      <App />
    </MemoryRouter>,
  )
}

describe("shared sidebar", () => {
  it("renders the sidebar with clinic identity and navigation", async () => {
    renderQueue()
    expect(await screen.findByText("Swasthiq Desk")).toBeInTheDocument()
    expect(screen.getByText("Sunrise Clinic, Dehradun")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /handoff queue/i })).toBeInTheDocument()
  })

  it("marks the handoff nav item active on /handoffs", async () => {
    renderQueue()
    const button = await screen.findByRole("link", { name: /handoff queue/i })
    expect(button.closest("[data-sidebar='menu-button']")).toHaveAttribute(
      "data-active",
      "true",
    )
  })
})

describe("handoff stats", () => {
  it("renders the real stats values", async () => {
    renderQueue()
    await waitFor(() => expect(screen.getByTestId("stats-grid")).toBeInTheDocument())
    const values = screen.getAllByTestId("stat-card").map(
      (card) => card.querySelector(".text-3xl").textContent,
    )
    // conversations | completed | escalated | urgent — all from real API data
    expect(values).toEqual(["6", "2", "6", "1"])
    expect(screen.getByText("33% of conversations")).toBeInTheDocument()
    expect(screen.getByText("2 still open")).toBeInTheDocument()
    expect(screen.getByText("clinical, unresolved")).toBeInTheDocument()
  })

  it("shows the open-count badge", async () => {
    renderQueue()
    await waitFor(() => {
      expect(screen.getByTestId("open-count-badge")).toHaveTextContent("2 OPEN")
    })
  })

  it("shows an error state when stats fail", async () => {
    api.get = () => Promise.reject(new ApiError("boom", 500))
    renderQueue()
    await waitFor(() => expect(screen.getAllByTestId("error-state").length).toBeGreaterThan(0))
  })
})

describe("handoff list", () => {
  it("renders each open handoff with caller context, reason and time", async () => {
    renderQueue()
    const rows = await screen.findAllByTestId("handoff-row")
    expect(rows).toHaveLength(2)
    expect(screen.getByText("Mujhe seena mein dard ho raha hai")).toBeInTheDocument()
    expect(screen.getByText("Sharma ji ke liye")).toBeInTheDocument()
    // readable label, machine value preserved as title
    const clinical = screen.getByText("Clinical").closest("[data-testid='reason-badge']")
    expect(clinical).toHaveAttribute("title", "clinical_urgent")
    expect(screen.getByText("Ambiguous Patient")).toBeInTheDocument()
  })

  it("links each row's conversation id to the detail route", async () => {
    renderQueue()
    const link = await screen.findByRole("link", { name: "cv_0011" })
    expect(link).toHaveAttribute("href", "/conversations/cv_0011")
  })

  it("shows the empty state when there are no open handoffs", async () => {
    api.get = (path) => {
      if (path === "/api/handoffs?status=open") return Promise.resolve({ handoffs: [] })
      if (path === "/api/conversations") return Promise.resolve(conversationsFixture)
      return Promise.resolve(statsFixture)
    }
    renderQueue()
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeInTheDocument())
    expect(screen.getByText(/queue is clear/i)).toBeInTheDocument()
  })
})

describe("resolve action", () => {
  it("resolves a handoff and refreshes list and counters", async () => {
    const user = userEvent.setup()
    let openNow = handoffsFixture
    api.patch = (path) => {
      api.calls.push({ path, method: "PATCH" })
      openNow = { handoffs: openNow.handoffs.filter((h) => h.conversation_id !== "cv_0011") }
      return Promise.resolve({ conversation_id: "cv_0011", status: "resolved", resolved_at: null })
    }
    api.get = (path) => {
      if (path === "/api/handoffs?status=open") return Promise.resolve(openNow)
      if (path === "/api/conversations") return Promise.resolve(conversationsFixture)
      return Promise.resolve(statsFixture)
    }

    renderQueue()
    const button = await screen.findByTestId("resolve-cv_0011")
    await user.click(button)

    expect(api.calls.some((c) => c.method === "PATCH" && c.path === "/api/handoffs/cv_0011/resolve")).toBe(true)
    await waitFor(() => {
      expect(screen.queryByTestId("resolve-cv_0011")).not.toBeInTheDocument()
    })
  })

  it("shows an error and keeps the row when resolve fails", async () => {
    const user = userEvent.setup()
    api.patch = () => Promise.reject(new ApiError("boom", 500))
    renderQueue()
    const button = await screen.findByTestId("resolve-cv_0011")
    await user.click(button)
    await waitFor(() => expect(screen.getByTestId("resolve-error")).toBeInTheDocument())
    expect(screen.getByTestId("resolve-cv_0011")).toBeInTheDocument()
  })

  it("prevents duplicate concurrent submissions", async () => {
    const user = userEvent.setup()
    let pending
    api.patch = (path) => {
      api.calls.push({ path, method: "PATCH" })
      return new Promise((resolve) => { pending = resolve })
    }
    renderQueue()
    const button = await screen.findByTestId("resolve-cv_0011")
    await user.click(button)
    await user.click(button) // second click while in flight
    expect(api.calls.filter((c) => c.method === "PATCH")).toHaveLength(1)
    pending({ conversation_id: "cv_0011", status: "resolved", resolved_at: null })
  })
})
