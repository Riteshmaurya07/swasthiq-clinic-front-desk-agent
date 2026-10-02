import { useState } from "react"
import { Loader2, LockKeyhole, Stethoscope, TriangleAlert } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

/**
 * Sign-in screen for the session-protected dashboard (H-2).
 *
 * Holds no credential of its own: the password lives in this component's state
 * only for the duration of the submit, is sent straight to POST /api/auth/login,
 * and is cleared immediately afterwards. It is never written to localStorage,
 * sessionStorage, a cookie readable by JS, or the URL.
 */
export function LoginPage({ onSignIn }) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await onSignIn(username, password)
      setPassword("")
    } catch {
      // Deliberately vague: the server already refuses to say whether it was the
      // username or the password that was wrong, and so do we.
      setError("Sign-in failed. Check the dashboard credentials and try again.")
      setPassword("")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-6">
      <Card className="w-full max-w-sm" data-testid="login-page">
        <CardHeader>
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Stethoscope className="size-4" />
            </div>
            <CardTitle className="text-lg">Swasthiq Desk</CardTitle>
          </div>
          <CardDescription>
            Sunrise Clinic, Dehradun — staff access to the handoff queue
          </CardDescription>
        </CardHeader>

        <form onSubmit={handleSubmit}>
          <CardContent className="flex flex-col gap-4">
            {error ? (
              <Alert variant="destructive" data-testid="login-error">
                <TriangleAlert />
                <AlertTitle>Sign-in failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="dashboard-username">Username</Label>
              <Input
                id="dashboard-username"
                name="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="dashboard-password">Password</Label>
              <Input
                id="dashboard-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>

            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <LockKeyhole className="mt-0.5 size-3 shrink-0" />
              Credentials are configured on the server. This dashboard shows patient
              conversations and clinical handoffs, so it is never served unauthenticated.
            </p>
          </CardContent>

          <CardFooter className="pt-0">
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? <Loader2 className="animate-spin" /> : null}
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}