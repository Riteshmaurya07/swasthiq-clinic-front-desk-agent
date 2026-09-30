/**
 * Human-readable labels for machine values. The underlying machine value is
 * always preserved and shown in the UI (mockup: mono values in the outcome
 * panel); these labels only affect presentation.
 */

export const ESCALATION_LABELS: Record<string, string> = {
  clinical_urgent: "Clinical",
  medical_advice: "Medical Advice",
  not_authorised: "Not Authorised",
  not_authorized: "Not Authorised",
  ambiguous_patient: "Ambiguous Patient",
  out_of_scope: "Out of Scope",
}

export const TERMINAL_STATE_LABELS: Record<string, string> = {
  booked: "Booked",
  rescheduled: "Rescheduled",
  cancelled: "Cancelled",
  escalated: "Escalated",
  refused: "Refused",
  abandoned: "Abandoned",
}

export function escalationLabel(reason: string | null | undefined): string {
  if (!reason) return "Unknown"
  return ESCALATION_LABELS[reason] ?? reason
}

export function terminalStateLabel(state: string | null | undefined): string {
  if (!state) return "Unknown"
  return TERMINAL_STATE_LABELS[state] ?? state
}

/** Badge color treatment per escalation reason (matches mockup groupings). */
export function escalationBadgeVariant(reason: string): "clinical" | "warning" | "amber" {
  if (reason === "clinical_urgent" || reason === "medical_advice") return "clinical"
  if (reason === "not_authorised" || reason === "not_authorized") return "warning"
  return "amber"
}

/** HH:MM from an ISO-ish timestamp; returns the raw string when unparseable. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
}
