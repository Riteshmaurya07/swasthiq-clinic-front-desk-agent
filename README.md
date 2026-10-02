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
    main.py             # FastAPI: POST /agent/run + dashboard APIs + CORS
    agent/
      engine.py         # conversation orchestration (deterministic)
      understanding.py  # Hinglish/English turn parser (regex/stateless)
      clinical_urgency.py  # context-aware emergency detector (symptom groups + context gates)
      state.py          # per-conversation state machine
      guard.py          # strict model-output validator (fail-closed)
      doctor_resolver.py
      engine_utils.py
    tools/              # the six tools + shared helpers + identity resolution
    persistence/        # SQLite display layer (database, models, repositories, timeline)
  tests/                # 438 tests (synthetic fixture — no confidential data)
                        #   includes 117 H-3 emergency-detection regressions,
                        #   30 C-1..C-4 red-team regressions
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

Health check: `curl http://localhost:8000/health` → `{"status":"ok","persistence_failures":0}` — public, no credentials needed.

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
| `POST /agent/run` | the public conversational API |
| `GET /health` | liveness + persistence-failure counter |



### Production deployment requirements

- Serve over HTTPS.
- Set `BACKEND_CORS_ORIGINS` to the deployed frontend origin. The origin list must stay explicit — never `*`.

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
2. **Acute clinical emergency** → immediate `escalated/clinical_urgent`, no mutation tools.
3. **Medical advice and triage questions** → `escalated/medical_advice`.
4. A booking flow interrupted by an emergency never resumes — escalation is terminal.

The same safety check runs again after every turn completes, so an emergency
arriving *after* a booking was already committed still overrides the outcome
(terminal state becomes `escalated`, the already-recorded action stands, and
nothing further may be scheduled).
### Context-aware emergency detection

Emergency detection (`backend/app/agent/clinical_urgency.py`) is **not** a flat
keyword matcher. A turn is analysed as **symptom groups** — breathing distress,
loss of consciousness, named cardiac/stroke events, chest pain, bleeding,
severe pain, acute abdominal complaints, high fever, trauma, dizziness, severe
allergic reaction, impending collapse — each with its own requirements, and
then each **candidate match is filtered through context gates** before it
counts as an emergency:

- **Severity gate** — vague complaints (`mujhe bukhar hai`) only escalate with
  an intensifier, a complication, a destination, or a measured high value
  (`bukhar 104 degree`).
- **Temporal scope** — completed-past and resolved-complaint markers are matched
  against the *clause containing the symptom*, so a historical or second-hand
  report does not escalate.
- **Present-tense re-arm** — an explicit "ab bhi" / "ab … ho raha" defeats that
  suppression: `chest pain tha, ab bhi hai` is about now.
- **Discourse framing** — illustrative frames (`example ke liye`, `jaise`) are
  turn-wide; local hypotheticals (`agar`, `suna hai`) are clause-scoped.
- **Proximity negation with binding breakers** — `nahi` suppresses the symptom it
  sits next to, but a conjunction between the negation and the symptom shows the
  negation belongs to something else, so `maine goli nahi khayi aur bahut tez
  bukhar hai` keeps the fever.
- **Breathing exception** — in `saans nahi aa rahi` the negation *is* the
  symptom, so that group is exempt from the negation gate while symptom nouns
  such as `breathlessness` obey it normally.
- **Diminishers** — `halka`, `thoda sa`, `mild`, `slight` downgrade a vague
  symptom, bound positionally so they cannot downgrade a different symptom in
  the same sentence.

An explicit **historical or non-acute report is deliberately suppressed** rather
than escalated.

**Triage is routed separately from an acute emergency.** "Kya mujhe hospital jaana
chahiye?" / "should I go to hospital?" are not reported symptoms, so they do not
claim `clinical_urgent`; they still reach a human as `escalated/medical_advice`.
When a real symptom appears in the same turn it takes precedence and the turn is
`clinical_urgent`.

**Why false-positive control matters more here.** Because emergency escalation
overrides an already-completed action (C-1), an unnecessary emergency destroys a
booking that was already correctly made. Suppressing a historical clause is the
safer error, so the detector is tuned to favour precision where recall is
ambiguous. The known limitations are — English coverage is thinner than Hindi/Hinglish, the
gates are positional windows rather than full syntactic parsing, and thresholds
are corpus-tuned rather than clinically validated.

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
# backend — 438 tests
python -m pytest -q

# frontend - 23 tests
cd frontend && npm test

# production build
cd frontend && npm run build
```

*Note: the confidential starter/evaluator pack supplied for the hiring assignment is not included in this public repository. The public repository can be tested with the included pytest suite, frontend tests, and the authored adversarial cases.*

## Verified results (final audit)

| Check | Result |
|---|---|
| Backend pytest | **438 passed** (1 deprecation warning from starlette's testclient) |
| Frontend tests | **23 passed** |
| Production build | success |
| Adversarial cases | **8/8 scenarios**, 0 failures (plus 20 adversarial unit tests) |
| H-3 emergency regressions | **117 passed**; 74 of the 117 fail against the pre-H-3 detector, so the suite is load-bearing rather than a restatement of current behaviour |
| C-1..C-4 red-team regressions | **30 passed** |
| Mutation safety | **0** unauthorized mutations, **0** post-terminal mutation leaks |
| Determinism | **0** non-deterministic results across the repeated-run corpus |
| Emergency corpus recall | 37/40 realistic phrasings detected; 0 false-positive urgency on medical-advice phrasings (15/15 advice phrasings routed) |
| `git diff --check` | clean |

## Model used, token and latency behavior

- **Model: none.** The agent is a deterministic rule-based engine (`model=None`); no LLM API is called anywhere in request handling.
- **Tokens: 0** for every conversation — reported honestly because no model consumes tokens. The outcome panel states this explicitly rather than implying LLM usage.
- **Latency:** real per-request wall time (monotonic clock), typically ~15–40 ms per conversation locally; persisted per conversation and shown in the dashboard.

## Known limitations

- No per-tool results are persisted (the request/response contract exposes tool name/arguments only); the UI shows arguments, never invented results.
- The deterministic parser covers the Hinglish/English patterns in the test and adversarial suites; arbitrary phrasings outside those patterns fail safe (abandon or escalate) rather than guess.
- Emergency detection (H-3) is context-aware but **not clinically validated**. Its thresholds are tuned against our own corpus, not against clinical guidance:
  - **English coverage is thinner** than Hindi/Hinglish coverage, and there is no language-detection fallback, so unlisted English synonyms can still be missed.
  - **Context gates are positional windows**, not full syntactic parsing — a negation far from its noun, or a symptom buried inside a deeply nested clause, can bind incorrectly.
  - A vague complaint with no severity marker (`mujhe bukhar hai`) is intentionally **not** escalated, so a caller who under-reports severity is not caught on the emergency channel.
  - The historical-suppression and present-tense re-arm rules are coarse (turn-wide rather than per-clause).
  - Recall is measured on our corpus, not asserted as complete; 37 of 40 realistic emergency phrasings are detected, and the 3 undetected ones are deliberate (insomnia is not acute; two triage questions route to `medical_advice` instead).
- The dashboard list endpoints are bounded (200 newest conversations) without pagination.
- `latency_ms` reflects the local machine; production numbers will differ.
- Backend dependencies in `requirements.txt` are not version-pinned (the frontend lockfile is committed).

- **Live deployment:** The dashboard is live at [https://frontend-omega-sable-e1wat5r269.vercel.app](https://frontend-omega-sable-e1wat5r269.vercel.app). The backend API is hosted at `https://swasthiq-clinic-front-desk-agent.onrender.com`.

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
4. Set `CLINIC_JSON_PATH=backend/tests/fixtures/clinic_fixture.json` in the backend environment to use the public synthetic clinic data for the live demo.
5. The SQLite file is created at `backend/data/app.db` — mount a persistent volume if dashboard history must survive restarts.


One command for local evaluation of everything:

```bash
# terminal 1 (repo root)
python -m uvicorn backend.app.main:app --port 8000
# terminal 2 (repo root)
cd frontend && npm install && npm run dev
```
