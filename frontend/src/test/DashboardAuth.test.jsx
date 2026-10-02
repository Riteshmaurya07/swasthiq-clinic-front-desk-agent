import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import { ApiError, login, logout } from "@/lib/api"
import { conversationsFixture, handoffsFixture, mockApi, mockSession, statsFixture } from "./fixtures"

/**
 * H-2 frontend regression: the dashboard must sit behind a sign-in screen, must
 * send credentials so the HttpOnly cookie travels, and must drop the operator
 * back to login on a 401.
 */

let api
let session

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    fetchHandoffs: vi.fn(() => api.get("/api/handoffs?status=open")),
    fetchHandoffStats: vi.fn(() => api.get("/api/handoffs/stats")),
    fetchConversations: vi.fn(() => api.get("/api/conversations")),
    fetchConversation: vi.fn((id) => api.get(`/api/conversations/${id}`)),
    resolveHandoff: vi.fn((id) => api.patch(`/api/handoffs/${id}/resolve`)),
    fetchSession: vi.fn(() => session.me()),
    login: vi.fn((u, p) => session.login(u, p)),
    logout: vi.fn(() => session.logout()),
  }
})

beforeEach(() => {
  api = mockApi()
  session = mockSession()
  vi.clearAllMocks()
})

afterEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})

function renderApp(path = "/handoffs") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe("dashboard login gate", () => {
  it("shows the sign-in screen and loads no dashboard data when signed out", async () => {
    renderApp()
    expect(await screen.findByTestId("login-page")).toBeInTheDocument()

    // The whole point: no conversation or handoff request is issued.
    expect(api.calls).toEqual([])
    expect(screen.queryByText("Handoff Queue")).not.toBeInTheDocument()
    expect(screen.queryByTestId("stats-grid")).not.toBeInTheDocument()
  })

  it("checks the existing session before rendering protected content", async () => {
    renderApp()
    await screen.findByTestId("login-page")
    expect(session.calls).toContainEqual({ path: "/api/auth/me", method: "GET" })
  })

  it("signs in with the entered credentials and reveals the dashboard", async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId("login-page")

    await user.type(screen.getByLabelText(/username/i), "desk-operator")
    await user.type(screen.getByLabelText(/password/i), "widget-2026")
    await user.click(screen.getByRole("button", { name: /sign in/i }))

    expect(await screen.findByTestId("stats-grid")).toBeInTheDocument()
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument()
    expect(login).toHaveBeenCalledWith("desk-operator", "widget-2026")
  })

  it("shows an error and stays on the login screen when credentials are wrong", async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId("login-page")

    await user.type(screen.getByLabelText(/username/i), "desk-operator")
    await user.type(screen.getByLabelText(/password/i), "wrong-password")
    await user.click(screen.getByRole("button", { name: /sign in/i }))

    expect(await screen.findByTestId("login-error")).toBeInTheDocument()
    expect(screen.getByTestId("login-page")).toBeInTheDocument()
    expect(api.calls).toEqual([]) // still no dashboard data requested
  })

  it("masks the password field", async () => {
    renderApp()
    await screen.findByTestId("login-page")
    expect(screen.getByLabelText(/password/i)).toHaveAttribute("type", "password")
  })

  it("never persists the password in web storage", async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId("login-page")

    await user.type(screen.getByLabelText(/username/i), "desk-operator")
    await user.type(screen.getByLabelText(/password/i), "widget-2026")
    await user.click(screen.getByRole("button", { name: /sign in/i }))
    await screen.findByTestId("stats-grid")

    const stored = JSON.stringify({ ...window.localStorage, ...window.sessionStorage })
    expect(stored).not.toContain("widget-2026")
    expect(stored).not.toContain("desk-operator")
  })

  it("never renders the operator's username once signed in", async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId("login-page")

    await user.type(screen.getByLabelText(/username/i), "desk-operator")
    await user.type(screen.getByLabelText(/password/i), "widget-2026")
    await user.click(screen.getByRole("button", { name: /sign in/i }))
    await screen.findByTestId("stats-grid")

    // The session is an anonymous bearer capability: the API layer never returns a
    // username, so the signed-in UI has nothing to display and nothing to leak.
    expect(document.body.textContent).not.toContain("desk-operator")
    expect(screen.getByTestId("session-state")).toBeInTheDocument()
  })

  it("does not put credentials in the request URL", async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId("login-page")

    await user.type(screen.getByLabelText(/username/i), "desk-operator")
    await user.type(screen.getByLabelText(/password/i), "widget-2026")
    await user.click(screen.getByRole("button", { name: /sign in/i }))
    await screen.findByTestId("stats-grid")

    for (const call of session.calls) {
      expect(call.path).not.toContain("widget-2026")
    }
  })
})

describe("signed-in dashboard", () => {
  beforeEach(() => {
    session.signIn()
  })

  it("loads the protected dashboard for an existing session", async () => {
    renderApp()
    expect(await screen.findByTestId("stats-grid")).toBeInTheDocument()
    // Sidebar nav item and page heading both read "Handoff Queue"; assert the heading.
    expect(screen.getByRole("heading", { name: /handoff queue/i })).toBeInTheDocument()
  })

  it("shows handoff rows as before authentication", async () => {
    renderApp()
    const rows = await screen.findAllByTestId("handoff-row")
    expect(rows).toHaveLength(2)
    expect(screen.getByText("Mujhe seena mein dard ho raha hai")).toBeInTheDocument()
  })

  it("keeps the conversation detail page working", async () => {
    renderApp("/conversations/cv_0011")
    await waitFor(() =>
      expect(screen.getByTestId("detail-title")).toHaveTextContent("Conversation cv_0011"),
    )
  })

  it("signs out and returns to the login screen", async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId("stats-grid")

    await user.click(screen.getByTestId("sign-out"))

    expect(await screen.findByTestId("login-page")).toBeInTheDocument()
    expect(logout).toHaveBeenCalled()
  })
})

describe("expired session handling", () => {
  beforeEach(() => {
    session.signIn()
  })

  it("returns the user to the login screen when the queue call is a 401", async () => {
    api.get = (path) => {
      if (path === "/api/handoffs?status=open") {
        return Promise.reject(new ApiError("Session ended", 401))
      }
      if (path === "/api/conversations") return Promise.resolve(conversationsFixture)
      return Promise.resolve(statsFixture)
    }
    renderApp()
    expect(await screen.findByTestId("login-page")).toBeInTheDocument()
  })

  it("returns the user to the login screen when a resolve is a 401", async () => {
    const user = userEvent.setup()
    api.patch = () => Promise.reject(new ApiError("Session ended", 401))
    renderApp()
    const button = await screen.findByTestId("resolve-cv_0011")
    await user.click(button)
    expect(await screen.findByTestId("login-page")).toBeInTheDocument()
  })

  it("returns the user to the login screen when a conversation detail is a 401", async () => {
    api.get = (path) => {
      if (path === "/api/conversations/cv_0011") {
        return Promise.reject(new ApiError("Session ended", 401))
      }
      if (path === "/api/handoffs?status=open") return Promise.resolve(handoffsFixture)
      return Promise.resolve(statsFixture)
    }
    renderApp("/conversations/cv_0011")
    expect(await screen.findByTestId("login-page")).toBeInTheDocument()
  })

  it("keeps showing the queue on a non-401 failure", async () => {
    api.get = (path) => {
      if (path === "/api/handoffs?status=open") return Promise.resolve(handoffsFixture)
      if (path === "/api/conversations") return Promise.resolve(conversationsFixture)
      return Promise.reject(new ApiError("boom", 500))
    }
    renderApp()
    expect(await screen.findAllByTestId("error-state")).not.toHaveLength(0)
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument()
  })
})

describe("api layer credentials", () => {
  it("sends credentials on every dashboard request so the cookie travels", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ conversations: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    const actual = await vi.importActual("@/lib/api")
    await actual.fetchConversations()
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/conversations",
      expect.objectContaining({ credentials: "include" }),
    )
    fetchSpy.mockRestore()
  })

  it("normalizes a 401 into an ApiError carrying status 401", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "nope" }), { status: 401 }),
    )
    const actual = await vi.importActual("@/lib/api")
    await expect(actual.fetchHandoffs()).rejects.toMatchObject({ name: "ApiError", status: 401 })
    fetchSpy.mockRestore()
  })

  it("posts the login request as JSON with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    const actual = await vi.importActual("@/lib/api")
    await actual.login("someone", "some-password")
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/auth/login")
    expect(init.method).toBe("POST")
    expect(init.credentials).toBe("include")
    expect(JSON.parse(init.body)).toEqual({ username: "someone", password: "some-password" })
    fetchSpy.mockRestore()
  })
})