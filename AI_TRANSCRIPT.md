# AI_TRANSCRIPT.md

Major prompts given to the coding assistant (Codebuff / Freebuff), phase by
phase. Prompts are reproduced essentially as issued; references to the
confidential supplied materials are summarized rather than reproduced. These
prompts document how the agent was directed — they do not republish the
assignment's source files.

> Context (necessary background, not confidential content): the project is a
> clinic front-desk conversational agent with six deterministic scheduling
> tools, a strict safety/escalation layer, and a React dashboard with a
> Handoff Queue and a Conversation Detail screen. The evaluation harness and
> example conversations were supplied privately and are not included here.

---

## Phase 0 — Requirements analysis

> Analyze the assignment PDF in this workspace. Extract the full brief to a
> private notes file, write PROJECT_REQUIREMENTS.md capturing every
> requirement and constraint, and IMPLEMENTATION_PLAN.md with a phased plan.
> Do not write application code yet.

## Phase 1 — Domain layer

> Implement the pure clinic domain layer in backend/app/clinic.py: load the
> clinic data into an immutable object, get_available_slots with 15-minute
> grid alignment and merged overlapping windows, holiday and leave handling,
> strict YYYY-MM-DD parse_date, and NO system-clock usage anywhere. Add
> pytest with a tmp_path copy of the clinic data so the original can never be
> mutated.

## Phase 2 — Tool layer

> Implement the six tools (search_slots, book_appointment,
> reschedule_appointment, cancel_appointment, lookup_patient,
> escalate_to_human) as deterministic functions returning ToolResult
> ok/error with specific machine-readable error codes. AppointmentStore must
> be thread-safe, re-check slot availability at mutation time, and continue
> the supplied ap_NNNN id sequence. Identity resolution: exact normalized
> full-name match, ambiguous names return all candidates and never pick. Add
> a barrier-raced concurrency test proving two callers cannot book the same
> slot.

## Phase 3 — Conversation engine

> Build the deterministic conversation layer: a Hinglish/English
> regex/stateful turn parser (understanding.py), ConversationState with
> intent/identity/date/time tracking, and the ConversationEngine pipeline
> understand → safety pre-check → identity → request params → intent →
> gated tools. All supplied conversations must pass through the engine
> directly. model=None — no LLM anywhere.

## Phase 4 — REST API

> Wrap the engine in FastAPI POST /agent/run: Pydantic request validation
> failing 4xx (never repair), response validation against the supplied
> schema failing closed to 500 on internal corruption, fresh clinic+store
> per request, metrics with real monotonic latency and honest token
> reporting. Integration tests over real HTTP including isolation and
> determinism.

## Phase 5 — Safety/authorization audit + hardening

> Run a full audit against the supplied conversations: verify the
> authorization model (guardian_of only, shared phone is NOT authorization —
> the data contains a deliberate shared-phone trap), injection markers,
> initials in names, and rewrite the date-signal logic so day+weekday must
> be consistent, contradictions resolve by recency, and a later weekday
> defers to an explicit day mention. Add regression tests for every fix.

Correction prompt that changed behavior:
> The family-phone fallback you added is wrong — remove it. Authorization
> ONLY via self or guardian_of listing. First-name dependent resolution must
> be scoped to the caller's guardian_of list.

## Phase 6 — Adversarial cases

> Write eight adversarial conversation scripts in the same JSON format the
> harness uses (adversarial/case_0001..0008.json) that break a naive
> implementation: emergency-after-progress, shared-phone false
> authorization, ambiguous bare name + cancel, guardian twin collision,
> occupied→alternative slot, mid-booking injection, corroborating date
> signals, dependent identity correction. One line each on why a naive agent
> fails. Then fix whatever real bugs they expose in MY engine — including a
> nameless dependent mention booking the caller, target corrections ignored,
> relationship-prefixed names, and "X hi hoon" self-identification — with
> permanent regression tests. Do not weaken the evaluator contract.

## Phase 7 — SQLite persistence + read APIs

> Add a SQLite application persistence layer (backend/app/persistence/) for
> dashboard display state ONLY: conversations, ordered tool-call traces with
> sequence numbers, handoffs (open/resolved) created only for escalations.
> Keep it strictly separate from the evaluator's request-isolated
> appointment state; persistence failure must never change the /agent/run
> response. Add read APIs: GET /api/conversations, GET
> /api/conversations/{id}, GET /api/handoffs, GET /api/handoffs/stats, PATCH
> /api/handoffs/{id}/resolve (deterministic, idempotent, 404 unknown). Add a
> minimal turn-indexed tool-event trace inside the engine without altering
> the evaluator contract. Then run the full evaluator regression.

Correction prompt that changed behavior:
> The transcript's final agent event stores a placeholder instead of the
> actual reply text — the frontend needs the real text. Smallest possible
> fix plus a regression test; do not change the HTTP contract.

## Phase 8 — React frontend

> Build the React frontend with Vite + Tailwind + shadcn/ui: exactly two
> screens (/handoffs and /conversations/:id) plus a shared persistent
> sidebar, matching the assignment mockups' structure. Handoff Queue: real
> stat cards, open-handoff table, resolve with loading/duplicate/error
> handling, empty state. Conversation Detail: transcript with every tool
> call inline at its persisted sequence position, expandable JSON arguments,
> machine-readable outcome panel with truthful values (null stays null,
> tokens honestly 0). Central API client with VITE_API_BASE_URL. No fake
> data, no fabricated tool results, no competing UI framework. Frontend
> tests for all required cases, production build, then browser-validate
> against the live backend and re-run all backend regressions.

Mid-phase correction (from browser validation):
> The Conversations stat card shows the handoff total instead of the
> stored-conversation count — derive each counter card from the correct
> endpoint and add a fetchConversations call. Keep all values from real API
> data.

## Phase 9 — Documentation + final audit

> Final documentation and submission audit only — no new features, no
> per-tool-result persistence: README.md (all required sections, honest
> model/token/latency statements), DECISIONS.md
> (Problem/Decision/Reason/Alternative/Tradeoff for every major choice),
> AI_TRANSCRIPT.md (this file), .gitignore + .env.example, FINAL_AUDIT.md
> requirement matrix with verified evidence, rerun the complete test audit
> (pytest, harness runs, repeat-3, npm test, build), verify supplied-file
> integrity, and a secret/machine-path scan. Do not mark anything complete
> unless actually verified.

## Phase 10 — Git initialization

> Stop the dev servers, initialize git, verify .gitignore excludes all
> runtime artifacts, review the full status, make the initial checkpoint
> commit, and re-run the complete verification. Never commit secrets,
> databases, virtual environments, node_modules, or build artifacts.

## Phase 11 — Public repository preparation

> The assignment materials are confidential: prepare a SEPARATE public
> repository copy containing only our own implementation, tests,
> documentation, and adversarial cases. Exclude the assignment PDF, the
> extracted brief, the extracted mockups, and the entire supplied starter
> pack. Review this AI transcript for confidential reproduction, add a
> provenance note to the README, verify with a fresh git history, and run
> the full test suite from the public copy alone.
