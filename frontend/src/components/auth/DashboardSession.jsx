import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"

import { fetchSession, isUnauthorized, login as apiLogin, logout as apiLogout } from "@/lib/api"
import { LoginPage } from "@/pages/Login"

/**
 * Dashboard session gate (H-2 remediation).
 *
 * The dashboard APIs are session-protected. This provider asks the server
 * whether a valid session exists on mount and renders one of three things:
 *
 *   checking   -> a neutral loading state (never the protected layout)
 *   signed-out -> <LoginPage />
 *   signed-in  -> the dashboard, exactly as before
 *
 * It holds no identity. The server answers `/api/auth/me` with authentication
 * state only, so the configured username never reaches the browser, and the
 * password is never kept in JS state beyond the submit call. Nothing is written
 * to localStorage/sessionStorage: the session lives in an HttpOnly cookie the
 * browser replays automatically.
 *
 * `guard` lets any page hand a 401 back here, so an expired session drops the
 * operator onto the login screen instead of leaving them on a broken queue.
 */

const DashboardSessionContext = createContext(null)

export function DashboardSessionProvider({ children }) {
  const [status, setStatus] = useState("checking")

  useEffect(() => {
    let active = true
    fetchSession()
      .then(() => {
        if (!active) return
        setStatus("signed-in")
      })
      .catch(() => {
        // Any failure here (401 or an unreachable backend) means we cannot show
        // protected data, so the only safe render is the login screen.
        if (!active) return
        setStatus("signed-out")
      })
    return () => {
      active = false
    }
  }, [])

  const signIn = useCallback(async (user, password) => {
    await apiLogin(user, password)
    setStatus("signed-in")
  }, [])

  const signOut = useCallback(async () => {
    try {
      await apiLogout()
    } finally {
      // Local state clears even if the server call failed: a stale "signed in"
      // screen is worse than an unnecessary re-login.
      setStatus("signed-out")
    }
  }, [])

  /** Route a failed request back to the login screen when it was a 401. */
  const guard = useCallback((error) => {
    if (isUnauthorized(error)) setStatus("signed-out")
    return error
  }, [])

  const value = useMemo(
    () => ({ status, signIn, signOut, guard }),
    [status, signIn, signOut, guard],
  )

  return (
    <DashboardSessionContext.Provider value={value}>
      {status === "checking" ? (
        <div
          data-testid="session-checking"
          className="flex min-h-screen items-center justify-center text-sm text-muted-foreground"
        >
          Checking dashboard session…
        </div>
      ) : status === "signed-out" ? (
        <LoginPage onSignIn={signIn} />
      ) : (
        children
      )}
    </DashboardSessionContext.Provider>
  )
}

export function useDashboardSession() {
  const context = useContext(DashboardSessionContext)
  if (!context) {
    throw new Error("useDashboardSession must be used inside <DashboardSessionProvider>")
  }
  return context
}