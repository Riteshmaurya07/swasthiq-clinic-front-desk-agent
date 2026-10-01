# Swasthiq Clinic Front Desk Agent

A safe, deterministic clinic front-desk conversational agent for Sunrise Clinic, Dehradun — with six grounded scheduling tools, strict escalation rules, and a React operations dashboard (Handoff Queue + Conversation Detail).

Built for the Swasthiq / Kaagazy SDE Intern hiring assignment (September 2026).

---

## Assignment objective

Build a Python REST API exposing a conversational agent with six tools over a clinic's schedule, plus a React frontend with two screens:

1. **Handoff Queue** — counters, then the open handoffs the agent escalated, each with what the caller said, the reason, and a way to resolve it.
2. **Conversation Detail** — the transcript with every tool call shown inline exactly where it fired, and an outcome panel carrying the machine-readable result.

A shared sidebar persists across both screens.

The graded property is *safety with restraint*: escalate exactly when a human must take over (clinical emergency, medical advice, ambiguous identity, unauthorized third-party action), and otherwise complete ordinary booking/rescheduling/cancellation deterministically with **zero invented facts**.

---

## Architecture

```
Request (conversation_id, today, turns)
        │
        ▼
FastAPI  POST /agent/run          ← fresh clinic + fresh AppointmentStore per request
        │
        ▼
ConversationEngine (model=None)   ← deterministic Hinglish/English rule parser
   │  per turn: understand → safety pre-check → identity → request params
   │             → intent → (gated) tool call → state update
   ▼
Six deterministic tools           ← grounded ONLY in clinic.json; never call an LLM
        │
        ▼
Validated schema.md payload       ← fail-closed 500 if internal output is corrupt
        │
        ▼ (after the response is final)
SQLite application persistence    ← display records ONLY (never a scheduling source)
        │
        ▼
React dashboard  ←  GET /api/conversations, /api/handoffs, /api/handoffs/stats,
                    PATCH /api/handoffs/{id}/resolve
```

Key boundary: **evaluation state** (request-isolated, in-memory, clinic.json-derived) and **application display state** (SQLite) are separate. Nothing reads SQLite to schedule an appointment.

## Assignment materials (provenance note)

The Swasthiq hiring assignment and its supplied starter/evaluator materials
(clinic data, evaluation harness, output contract, and example conversation
scripts) are **confidential** — the assignment states they must not be
shared, published, or discussed publicly. They are therefore **not reproduced
in this public repository**:

- They were used privately during development (the private working copy
  contains them, unmodified, and the implementation was verified against
  them).
- This public repository contains what the assignment asks to be published:
  the application (`/backend`), the React frontend (`/frontend`), the eight
  **adversarial scripts we authored** (`/adversarial`), and the documentation
  (README, DECISIONS.md, AI_TRANSCRIPT.md).
- The public test suite runs entirely on a synthetic clinic fixture bundled
  at `backend/tests/fixtures/clinic_fixture.json` — no confidential data is
  required to develop or test.
- To run the agent locally, set `CLINIC_JSON_PATH` to any clinic data file
  with the same structure (see `.env.example` and the backend setup below).
- The request/response contract is documented in this README under
  "POST /agent/run contract".

## Repository structure

```
backend/
  app/
    clinic.py           # pure domain layer: load_clinic, available slots, windows, holidays
    store.py            # per-request AppointmentStore (thread-safe, slot re-check on mutation)
    errors.py           # ToolResult / ToolError with machine-readable codes
    schemas.py          # contract constants (terminal states, escalation reasons)
    main.py             # FastAPI: POST /agent/run + dashboard read APIs + CORS
    agent/
      engine.py         # conversation orchestration (deterministic)
      understanding.py  # Hinglish/English turn parser (regex/stateless)
      state.py          # per-conversation state machine
      guard.py          # strict model-output validator (fail-closed)
      doctor_resolver.py
      engine_utils.py
    tools/              # the six tools + shared helpers + identity resolution
    persistence/        # SQLite display layer (database, models, repositories, timeline)
  tests/                # 287 tests (synthetic fixture — no confidential data)
  tests/fixtures/clinic_fixture.json   # bundled synthetic clinic data
  data/app.db           # created lazily at runtime (gitignored)
frontend/
  src/
    api → lib/api.ts    # central API client (VITE_API_BASE_URL)
    components/ui/      # shadcn/ui components
    components/layout/  # AppSidebar (shared across routes)
    components/handoffs/ components/conversation/
    pages/              # HandoffQueue, ConversationDetail
    test/               # 23 vitest tests + API-shaped fixtures
adversarial/           # 8 adversarial scripts (authored by us, schema.md format)
```

## Backend setup (fresh clone)

Requires Python 3.11+. All commands below assume the **repository root** as the working directory (the directory containing `backend/`, `frontend/` and `adversarial/`) unless stated otherwise.

```bash
# working directory: repository root
python -m venv backend/.venv

# activate (bash/Git Bash):
source backend/.venv/bin/activate
# activate (Windows PowerShell):
backend\.venv\Scripts\Activate.ps1
# activate (Windows cmd):
backend\.venv\Scripts\activate.bat

# install dependencies (any working directory — the venv is already active)
pip install fastapi uvicorn pytest httpx

# point the API at a clinic data file (structure documented in "POST /agent/run
# contract" and matches the schema used by backend/tests/fixtures/clinic_fixture.json).
# PowerShell:      $env:CLINIC_JSON_PATH = "path\to\clinic.json"
# bash/Git Bash:   export CLINIC_JSON_PATH=/path/to/clinic.json

# start the API — MUST be run from the repository root, because the app
# module path is backend.app.main:app
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Running `uvicorn` from inside `backend/` will fail with "app.main could not be imported" — always use the repository root for that command.

Health check: `curl http://localhost:8000/health` → `{"status":"ok","persistence_failures":0}`

Without `CLINIC_JSON_PATH`, `POST /agent/run` returns a clean error explaining the missing configuration (tests use the bundled synthetic fixture automatically).

`backend/data/app.db` is created automatically on first request; delete it to reset dashboard data.

## Frontend setup (fresh clone)

Requires Node 18+.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 — proxies /api to localhost:8000
npm run build      # production bundle in dist/
npm test           # vitest suite
```

To point the frontend at a backend on another host, set `VITE_API_BASE_URL` (see `.env.example`).

## POST /agent/run contract

```json
// request
{ "conversation_id": "cv_0001", "today": "2026-10-01", "turns": ["...", "..."] }

// response (exactly this shape; matches schema.md)
{
  "conversation_id": "cv_0001",
  "tool_calls": [ { "name": "search_slots", "arguments": { "doctor_id": "dr_rao", "date": "2026-10-03" } } ],
  "terminal_state": "booked",            // booked|rescheduled|cancelled|escalated|refused|abandoned
  "escalation_reason": null,             // non-null only when escalated
  "patient_id": "pt_0013",
  "appointment_id": "ap_0026",
  "reply": "Ji, aapka appointment ...",
  "metrics": { "turns": 2, "tokens": 0, "latency_ms": 21 }
}
```

Malformed requests → 4xx (never repaired). Internal corruption → fail-closed 500, no bad payload emitted.

## Dashboard API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/conversations` | stored conversations (newest first) |
| `GET /api/conversations/{id}` | full detail: transcript, ordered tool_calls, outcome, metrics; 404 if unknown |
| `GET /api/handoffs?status=open\|resolved` | handoff queue rows |
| `GET /api/handoffs/stats` | `{total, open, resolved}` |
| `PATCH /api/handoffs/{id}/resolve` | deterministic open→resolved; idempotent; 404 unknown |
| `GET /health` | liveness + persistence-failure counter |

## The six deterministic tools

| Tool | Notes |
|---|---|
| `search_slots` | free 15-min grid slots from merged doctor windows minus booked appointments, holidays, leaves |
| `book_appointment` | re-checks slot at mutation time; race-safe (lock + conflict error) |
| `reschedule_appointment` | validates patient match + target slot before moving |
| `cancel_appointment` | marks cancelled; slots free up |
| `lookup_patient` | exact normalized full-name match; ambiguous names return all candidates, never pick |
| `escalate_to_human` | records the escalation; the only path to terminal `escalated` |

The tool layer never calls an LLM. It is the ground truth; everything the agent claims is checked against it.

## Safety architecture

Per-turn, **before** identity or any tool work:

1. **Prompt injection** → terminal `refused`, zero tool calls (not even escalate).
2. **Clinical urgency** (chest pain, breathlessness, …) → immediate `escalated/clinical_urgent`, no mutation tools.
3. **Medical advice requests** → `escalated/medical_advice`.
4. A booking flow interrupted by an emergency never resumes — escalation is terminal.

Malformed/off-schema model proposals (the architecture accepts an optional proposal model) pass through a strict validator and are dropped on any violation; they can never execute tools or set safety flags. This deployment runs with `model=None`.

## Authorization model

- A caller may act on **themselves**, or on a patient who **explicitly lists them in `guardian_of`**.
- **A shared phone number is NOT authorization** (clinic.json contains a deliberate trap: two patients share 9812200466 with no guardian link — the agent must refuse).
- Any unauthorized third-party action → `escalated/not_authorised`, no mutation.

## Identity resolution

- Exact normalized full-name match (tokenized; handles initials like "R. K. Sharma" without guessing).
- Ambiguous names (surname-only, bare first names, initials matching several patients) → `escalated/ambiguous_patient`, candidates never silently picked.
- Dependent resolution by first name is scoped to the caller's `guardian_of` list only.
- Third-party target corrections ("Aarav hai, Arjun nahi") take the last possessive mention; a mentioned-but-unresolved dependent fails closed (never books the caller instead).

## Deterministic date handling

- Every date resolves from the request's `today` — **never the system clock**.
- Relative tokens: `aaj` (today), `kal` (+1), `parso` (+2); weekday names resolve to the NEXT occurrence; day/month numbers roll forward when past.
- When multiple date signals appear, the last mention wins unless they corroborate; contradictory day+weekday pairs are resolved by consistency rules (a later weekday mention defers to explicit day+month, and vice versa per phase-5 audit).

## Request state isolation

Every `POST /agent/run` builds a fresh `Clinic` + `AppointmentStore`. Booking in request A can never influence request B — verified over real HTTP with order-dependent scenarios (book → re-book sees the slot free again).

## SQLite application persistence

After a `/agent/run` response is finalized, the run is recorded for the dashboard: conversation (turns, transcript timeline, terminal state, reason, ids, reply, metrics), ordered tool-call trace (sequence numbers, no fabricated timestamps), and — only for escalations — an open handoff with the caller's last statement. Persistence failures are logged and counted in `/health` but never alter the agent response or appointment state.

## Handoff Queue

Counters from real stats, open-handoff table (caller said / reason badge / time / resolve), resolve with in-flight spinner + duplicate-submission protection + idempotent success + error alert, professional empty state. All data from `GET /api/handoffs*`.

## Conversation Detail

Persisted transcript with CALLER/TOOL/AGENT rows; tool calls rendered inline at their sequence position with expandable JSON arguments; machine-readable outcome panel including literal `null`s where the backend returned null and truthful metrics (tokens = 0, honestly labeled).

## shadcn/ui usage

Sidebar, Card, Button, Badge, Table, Separator, Skeleton, Alert, Empty, Spinner, Collapsible, Tooltip, Sheet (sidebar mobile mode) — customized with Tailwind semantic tokens to match the assignment mockups' information architecture (stat-card row, dense table, blue-bordered tool blocks, right-hand outcome card). No competing UI framework.

## Testing

```bash
# backend — 287 tests
python -m pytest -q

# frontend — 23 tests
cd frontend && npm test

# production build
cd frontend && npm run build

*Note: The confidential starter/evaluator pack supplied for the hiring assignment is not included in this public repository. The public repository can be tested with the included pytest suite, frontend tests, and authored adversarial cases. The hidden evaluator supplies its own runner and starter materials.*
```

## Verified results (final audit)

| Check | Result |
|---|---|
| Backend pytest | **287 passed** (1 deprecation warning from starlette's testclient) |
| Frontend tests | **23 passed** |
| Production build | success |
| Supplied conversations | **15/15**, 0 failures |
| Adversarial cases | **8/8**, 0 failures |
| Repeat-3 determinism | deterministic across 3 runs (both dirs) |
| Browser validation | passed against live backend + dev server |
| Supplied-file integrity | runner/schema/clinic md5s unchanged; 15 + 8 scripts intact |

## Model used, token and latency behavior

- **Model: none.** The agent is a deterministic rule-based engine (`model=None`); no LLM API is called anywhere in request handling.
- **Tokens: 0** for every conversation — reported honestly because no model consumes tokens. The outcome panel states this explicitly rather than implying LLM usage.
- **Latency:** real per-request wall time (monotonic clock), typically ~15–40 ms per conversation locally; persisted per conversation and shown in the dashboard.

## Known limitations

- No per-tool results are persisted (the evaluator contract exposes tool name/arguments only); the UI shows arguments, never invented results.
- The deterministic parser covers the Hinglish/English patterns in the supplied + adversarial scripts; arbitrary phrasings outside those patterns fail safe (abandon or escalate) rather than guess.
- The dashboard list endpoints are bounded (200 newest conversations) without pagination.
- `latency_ms` reflects the local machine; production numbers will differ.
- Deployment not performed in this submission package (see below).

## Deployment instructions

Any static host + Python host pair works; nothing exotic is required.

**Frontend (Vercel / Netlify):**
1. `cd frontend && npm run build`
2. Deploy the `dist/` directory.
3. Set `VITE_API_BASE_URL=https://<your-api-host>` at build time (defaults to same-origin if you serve the API behind the same domain).

**Backend (any Python host / container):**
1. `pip install fastapi uvicorn`
2. `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` (from the repo root)
3. Set `BACKEND_CORS_ORIGINS=https://<your-frontend-origin>` in the backend environment so the deployed dashboard can call the API. Origins are comma-separated; the local Vite dev origins (`http://localhost:5173`, `http://127.0.0.1:5173`) always remain allowed for development. Wildcard `*` is never used.
4. The SQLite file is created at `backend/data/app.db` — mount a persistent volume if dashboard history must survive restarts.

One command for local evaluation of everything:

```bash
# terminal 1 (repo root)
python -m uvicorn backend.app.main:app --port 8000
# terminal 2 (repo root)
cd frontend && npm install && npm run dev
```
