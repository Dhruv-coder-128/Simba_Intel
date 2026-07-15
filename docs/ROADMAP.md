# SIMBA_INTEL — Feature Expansion Roadmap

Living document. Sequenced by real dependency order, not by wishlist order. Each phase is meant to
ship and be usable before the next one starts. Phases 1-5 have no external blockers and can be built
immediately; later phases have explicit blockers called out (API keys, OAuth consent, hosting
constraints, infra decisions) that need action from the project owner, not just code.

## Sequencing overview

| Phase | Item(s) | Why here |
|---|---|---|
| 1 | File upload -> chat context, Vision AI (image attach in chat), Text regenerate, PDF export, Camera AI | Zero new infra - reconnects code that already exists but is orphaned (`upload_file`, `ai_router.vision()`, `html2pdf.bundle.min.js`) |
| 2 | Theme toggle + presets, User profile/settings page, More AI providers | New but architecturally consistent; introduces first per-user settings model |
| 3 | Message edit + regenerate-as-branch (schema evolution) | Must happen before any later feature needing role-based/branching messages (compare, research agent transcripts, multi-agent discussion) |
| 4 | Usage/cost tracking + rate limiting | Needed before opening up multi-model and agentic features that multiply API cost |
| 5 | Analytics dashboard | Only depends on Phase 4's data |
| 6 | Postgres migration | Prerequisite for pgvector |
| 7 | pgvector semantic memory (cross-chat recall) | Needs Phase 6. Ships with `memory_enabled=False` by default |
| 8 | Persistent knowledge-base file search | Needs Phase 1 (extraction) + Phase 7 (embeddings) |
| 9 | Multi-model compare | Benefits from Phase 3's sibling-branch schema |
| 10 | Tool-calling framework | Generalizes the existing Tavily keyword heuristic; foundation for everything below |
| 11 | Browser/fetch tool ("read a web page") | Needed as a tool before the research agent can use it. Explicitly NOT autonomous browsing (no clicks, no forms, no JS execution) |
| 12 | Research agent | Needs Phase 10 + 11 |
| 13 | Coding agent / sandboxed execution | Real security decision point - see blocker below |
| 14 | Automation (scheduled agent runs) | New infra dependency (Celery + Redis) |
| 15 | Multi-agent discussion | Needs Phase 9 + Phase 3's schema |
| 16 | Email AI | Blocked on the owner's own Gmail OAuth/Google Cloud Console setup |
| 17 | Video AI adapter | Blocked on choosing + funding a video-gen provider |
| 18 | One-prompt -> working app/script | Last. Needs Phase 10 + 13 + 14 all working reliably first |

## Explicit blockers requiring owner action (not code)

- **Phase 13 (coding agent)**: the deployed hosting target (Render web service, per `ALLOWED_HOSTS`) does not
  support Docker-in-Docker. Spawning sandboxed execution containers needs either a different worker host or a
  hosted code-execution API. Must be decided before writing execution code.
- **Phase 14 (automation)**: adds Celery + Redis + a worker + a beat scheduler to `docker-compose.yml` - a real
  jump in operational complexity for a solo-run project. Worth confirming it's wanted before building.
- **Phase 16 (email AI)**: needs a Gmail API OAuth consent screen configured in Google Cloud Console, with
  `gmail.readonly`/`gmail.compose` scopes - sensitive-scope verification review can take days to weeks.
  Draft-only by design; never auto-sends.
- **Phase 17 (video AI)**: needs a paid provider (Runway/Luma/Kling/Veo/etc.) chosen and funded. Adapter shape
  can be designed in advance; nothing is testable until a real key exists.
- **Phase 18 ("one prompt -> app")**: has no general automatic correctness oracle. Scope should narrow to
  something checkable (e.g. a single-file script that must run without error against a known test input)
  rather than "a full working web app" - to be confirmed before building.

## Phase-by-phase detail

### Phase 1 - Reconnect dead code (no new infra)

- **File upload -> chat context**: `chat/views.py`'s `upload_file` already saves+analyzes a file via
  `chat/file_analyzer.py:analyze_file()` but nothing in `templates/chat.html` calls it. Add a file-attach
  control near the input bar; on the next `ask_ai` call, prepend the extracted text into the user query
  (delimited clearly), same pattern as today's Tavily search augmentation in `views.py`.
- **Vision AI**: `chat/services/ai_router.py:vision()` and `MistralProvider.vision()` already work but are
  never called. Add an image-attach control gated on `model_config.supports_vision`, build an OpenAI-style
  multimodal message, call `ai_router.vision()` (non-streaming for v1).
- **Text response regenerate**: mirror the existing image `regenerateImage()` button/flow for text replies.
  Simple "regenerate in place" now; full sibling-branch versioning arrives with Phase 3.
- **PDF export**: `html2pdf.bundle.min.js` is loaded via CDN and never invoked anywhere - wire an "Export PDF"
  button to it. Pure frontend, no backend change.
- **Camera AI**: `getUserMedia` capture -> canvas -> blob -> same upload+vision flow as Vision AI above. No new
  backend code beyond the vision branch.

### Phase 2 - Themes, profile/settings, more providers — DONE (July 2026, providers deferred by choice)

- ~~Theme presets~~ DONE: 4 themes (cyberpunk / midnight-purple / matrix-green / light) via
  `html[data-theme]` + a tokenized `--accent-rgb` scheme. Also removed the old CPU-load-based
  `--accent` inline override in `updateSystemStats` that force-reset the accent to cyan every second
  (it would have permanently stomped any theme).
- ~~`UserProfile` model~~ DONE: `chat/models.py` (display_name, avatar_url, default_model, theme,
  memory_enabled, notifications_enabled), migration `0008_userprofile`, lazily auto-created,
  registered in admin. `memory_enabled` is stored but dormant until Phase 7.
- ~~Settings page~~ DONE: `/settings/` (`profile_settings` view + `templates/profile.html`), linked
  from the sidebar. Live theme preview on selection; server-side validation of model/theme values.
  `notifications_enabled` gates the completion sound (`playBlip`).
- CSS/JS externalization into `static/simba/{css,js}/`: NOT done - deferred to whenever the next
  full page beyond profile.html gets built (analytics/knowledge base), to avoid churning the
  4000-line template twice.
- New providers: SKIPPED by owner choice for now (no API keys committed to). The `BaseProvider`
  pattern + `provider_manager.PROVIDER_REGISTRY` remain the single wiring point when wanted -
  OpenAI/DeepSeek/OpenRouter can share one OpenAI-compatible adapter class; Gemini needs the
  `google-genai` SDK.

### Phase 3 - Message schema evolution — DONE (July 2026)

Shipped exactly as designed, verified against real production chat history (22 sessions, 97 legacy turns):

- `Message` model (role, content, `parent` self-FK, `extra_data`, `latency`) + `ChatSession.active_leaf`,
  migrations `0009` (schema) + `0010` (data backfill, `chat/migrations/0010_backfill_message_tree.py`).
  `ChatMessage` is untouched and permanently intact as an audit/rollback copy - confirmed byte-for-byte
  unmodified after migration (97 rows before and after). A `db.sqlite3.pre-phase3-backup-*` snapshot was
  also taken before running the migration against the real dev DB, as a second safety net.
- `chat/services/message_tree.py` (new): `walk_chain_from`/`walk_active_chain`, `build_display_messages`
  (the chat_home read-adapter - re-pairs the tree into ChatMessage-shaped objects so `chat.html`'s render
  loop needed zero changes), `append_turn`, `regenerate_assistant_reply`. This is the module every later
  phase needing tree access (compare, research agent, multi-agent discussion) will import from.
- `chat/services/memory.py:get_conversation_history` now walks `active_leaf` instead of querying
  `ChatMessage` - `messages_to_history_dicts` is the shared chain-to-provider-format converter, reused by
  regenerate/edit for building context as-of an arbitrary historical message (not just the current leaf).
- `ask_ai`'s three write paths (text streaming, image-gen, vision) all write `Message` rows via
  `append_turn` now, not `ChatMessage.objects.create`.
- New endpoints with **real** sibling-branch semantics (not a "new turn" approximation):
  `POST /messages/<id>/regenerate/` and `POST /messages/<id>/edit/` both create a sibling under the
  original parent and move `active_leaf` there - the old branch stays in the DB, just off the active path.
  `GET /session/<id>/active-leaf/` lets the frontend learn a just-streamed message's real id (streaming
  responses can't carry a trailing id once the body has started).
- Frontend: `regenerateText()` and the new `editUserMessage()`/`submitEditedMessage()` replace a bubble's
  content in place via the new endpoints when a real message id is available (history-rendered messages
  always have one; live-streamed messages get one via the active-leaf fetch immediately after streaming
  completes, so branching works without a reload). Falls back to the old "append a new turn" behavior if
  no id is present, so regenerate never just breaks.
- Real bug caught by testing before it shipped: `append_turn`'s `parent=None` default couldn't distinguish
  "caller omitted the argument" from "caller explicitly wants a root-level parent," which broke editing the
  *first* message in a conversation (silently reparented under the wrong node). Fixed with a proper sentinel.
  Second bug caught the same way: `regenerateText`'s DOM update only touched `.content`'s children, leaving
  the old footer (copy/share/regenerate buttons + raw-data textarea) as untouched siblings - every
  regenerate was silently accumulating a duplicate footer. Both caught by writing/running tests and a live
  Playwright pass before declaring the phase done, not by inspection.
- Verified end-to-end in a real browser against the real Groq API: send -> regenerate (new sibling, old
  preserved, footer not duplicated) -> edit (new user+assistant branch, old preserved) -> page reload
  (history renders correctly via the adapter, ids correct) -> image generation (unaffected code path,
  confirmed still writes to the Message tree correctly). Zero console errors throughout. 52/52 automated
  tests passing (12 new: 6 migration correctness, 4 write-flow, 8 regenerate/edit endpoint - some overlap
  categories).

### Phase 4 - Usage & cost tracking, rate limiting — DONE (July 2026)

Corrected a wrong assumption from this section's original draft before writing any code: tested
`stream_options={"include_usage": True}` directly against both real APIs first. **Mistral's OpenAI-compatible
endpoint supports it and returns real token counts** (`CompletionUsage(prompt_tokens=5, completion_tokens=21,
...)`), but **the installed Groq SDK rejects the kwarg outright** (`TypeError: Completions.create() got an
unexpected keyword argument 'stream_options'`) - not "returns nothing," a hard error. Usage capture is
therefore provider-aware, not uniform:

- `UsageEvent` model (`chat/models.py`): user, session, provider, model_id, event_type (chat/vision/image),
  prompt_tokens, completion_tokens, estimated_cost_usd, `tokens_are_estimated` flag, latency, created_at.
  Migration `0011_usageevent`.
- `chat/services/cost_table.py`: static per-model USD/1k-token rates (approximate public list prices, not
  wired to a live pricing API - directional cost, not a billing-grade figure. Flagged in-file and in the
  analytics UI). `image-studio` (Pollinations) is a flat $0 - it's free.
- `chat/services/usage.py`: `estimate_tokens()` (`len(text)//4` heuristic), `record_usage()` (prefers real
  provider-supplied usage when given, falls back to the estimate otherwise), `check_rate_limit()` (DB-backed
  sliding window against `UsageEvent`, 30 requests/minute/user - no Redis, per this doc's original note to
  defer that until Phase 14 introduces it anyway).
- Real usage capture wired via an optional `on_usage` callback threaded through `chat_stream()`/`vision()`:
  `MistralProvider` calls it with real token counts from `stream_options`; `GroqProvider` accepts the same
  parameter (interface parity) but never calls it, so callers transparently fall back to the estimate - no
  branching logic needed at the call sites in `views.py`.
  `ai_router.supports_real_usage(model_id)` exists as a capability check if a future caller needs it directly.
- `UsageEvent.objects.create(...)` (via `record_usage`) wired into all 5 AI call sites: text streaming (main
  send + regenerate + edit), vision, and image generation.
  429 rate-limit responses added to `ask_ai`, `regenerate_message`, `edit_message`.
- 17 new tests (cost table, usage service, wiring at all 5 call sites, rate-limit enforcement). All passing
  against real Groq/Mistral calls, same pattern as Phase 3.

### Phase 5 - Analytics dashboard — DONE (July 2026)

Pure read-side view over Phase 4's `UsageEvent` data (`/analytics/`, `analytics_dashboard` view +
`templates/analytics.html`) - no writes happen here, so it's safe to hit as often as the user likes.

- Stat tiles (total requests, total tokens, estimated cost, avg latency), a 14-day requests line chart, a
  by-event-type doughnut, a by-model breakdown table, and a 20-row recent-activity table. Chart.js via CDN
  (consistent with this template's existing CDN usage for marked.js/DOMPurify/html2pdf).
  A footnote discloses when token counts shown are estimated vs. real, so the cost figures aren't mistaken
  for exact billing.
- Linked from the chat sidebar and the settings page. Reuses the same `data-theme` CSS custom-property
  scheme as `profile.html` so it matches whichever of the 4 themes the user has selected.
- 5 new tests (empty state, per-user isolation, aggregation correctness, estimated-token footnote logic).
  Verified live in a real browser with seeded data across all 4 themes and both light/dark rendering paths -
  zero console errors, charts render correctly.

### New UI features (outside the phase sequence, user-requested alongside Phase 4/5)

- **Command palette (Ctrl+K / Cmd+K)**: Raycast/Linear-style overlay, fuzzy-filterable list built live from
  the DOM each time it opens (new chat, analytics, settings, focus composer, focus search, log out, one
  entry per model in the dropdown, one entry per chat session in the sidebar) - no separate hardcoded data
  source to fall out of sync with what's actually on the page. Arrow keys + Enter + Escape, click-to-run.
- **Branch/sibling switcher**: Phase 3 gave regenerate/edit real sibling-branch semantics, but there was no
  UI to see or switch between the branches it created - this closes that gap. `build_display_messages()`
  now attaches sibling ids/index/count for both the assistant reply and the user turn (single extra query
  per session, not per-turn, via one bulk fetch + in-memory grouping). A `‹ 2/3 ›`-style pill appears in the
  reply footer (assistant siblings) and next to an edited user bubble (user siblings); clicking it calls the
  new `POST /messages/<id>/switch-branch/` endpoint, which moves `active_leaf` to the chosen sibling (or, for
  a user-message sibling, to its assistant child) and reloads to redraw the turn.
  New `GET /messages/<id>/siblings/` endpoint lets `regenerateText()`/`submitEditedMessage()` refresh the
  pill immediately after their in-place DOM patch, without a page reload - caught via a live Playwright check
  that the pill was otherwise silently missing until a manual refresh (server-side sibling data alone isn't
  enough when the frontend patches the DOM instead of re-rendering the template).
- 12 new backend tests (sibling-count correctness in `build_display_messages`, switch-branch endpoint
  semantics/ownership, siblings endpoint). Verified live end-to-end against the real Groq API: send ->
  regenerate -> switcher pill appears immediately showing 2/2 -> click switch -> lands back on 1/2 -> zero
  console errors.

### Phase 6 - Postgres migration

Add `dj-database-url` + `psycopg[binary]`, switch to `pgvector/pgvector:pg16` in `docker-compose.yml` (needed
by Phase 7 anyway - avoid a second image swap later). Migration procedure: `dumpdata` from SQLite -> `migrate`
on empty Postgres -> `loaddata` -> verify row counts match -> keep `db.sqlite3` on disk as rollback until
confidence is established. CI gets a Postgres service container.

### Phase 7 - Semantic memory (pgvector)

Ships with `memory_enabled=False` by default (per `UserProfile`), honoring the original guidance to defer
this until there's real usage to tune against. Embeddings via Mistral's `mistral-embed` (no new API key
needed). Generated synchronously best-effort after each assistant message (no Celery yet). Retrieval via
`CosineDistance`, injected into the system prompt as a clearly labeled block.

### Phase 8 - Persistent knowledge base

Builds on Phase 1's extraction + Phase 7's embeddings. `file_analyzer.py` currently truncates to 2000 chars -
needs a non-truncated `extract_text()` for this to be useful. New `KnowledgeDocument`/`KnowledgeChunk` models,
simple fixed-size overlapping chunker, retrieval merged with Phase 7's memory retrieval.

### Phase 9 - Multi-model compare

New `ai_router.chat_multi()` using a thread pool (sync Django, no async provider clients - threads are the
pragmatic choice) to call multiple models in parallel, non-streaming for v1. Results stored as sibling
`Message` rows under the same parent (first real payoff of Phase 3's schema).

### Phase 10 - Tool-calling framework

Generalizes the existing Tavily keyword-heuristic (`views.py:_is_search_query`/`_get_tavily_search`) into a
real `BaseTool` interface (mirrors `BaseProvider`'s shape) + registry + an `agent_runner` tool-calling loop
with a hard iteration cap. Needs verifying at implementation time that the Groq/Mistral SDKs accept a `tools`
kwarg through the existing passthrough.

### Phase 11 - Browser/fetch tool

Single-GET "read a page" tool using `requests` + `beautifulsoup4` (already an unused dependency - zero new
cost). Must ship with SSRF mitigation (reject private/loopback/link-local IP ranges, no auto-redirect
following without re-validating each hop) and prompt-injection mitigation (strip scripts/styles, wrap fetched
content in explicit untrusted-data delimiters) designed in from the start, not bolted on after.

### Phase 12 - Research agent

Search tool + fetch tool combined under `agent_runner` with a search -> fetch -> synthesize system prompt.
Tool-call steps shown as collapsible UI blocks, reusing the existing `<think>`-tag handling pattern already in
`sendQuery`'s streaming code.

### Phase 13 - Coding agent / sandboxed execution

Recommended: ephemeral Docker containers (`--network=none`, memory/CPU/PID limits, read-only mount,
wall-clock timeout) rather than raw subprocess limits (unreliable cross-platform, and this dev host is
Windows). Real blocker: the current Render hosting target doesn't support Docker-in-Docker - needs a
different execution host or a hosted code-exec API, decided before writing execution code.

### Phase 14 - Automation

Adds Celery + Redis + worker + beat services. New `ScheduledTask` model, Celery task wrapping `agent_runner`.
Tested with `CELERY_TASK_ALWAYS_EAGER=True`.

### Phase 15 - Multi-agent discussion

Builds on Phase 9's parallel-call infra + a turn-taking orchestrator where each model sees prior models'
responses. Persisted as tagged sibling `Message`s (third payoff of Phase 3's schema).

### Phase 16 - Email AI

Extends the existing django-allauth Google OAuth scopes to include Gmail. Read-only list/summarize now;
compose is draft-only forever unless a future phase explicitly adds a separate, per-message confirmed send
action.

### Phase 17 - Video AI adapter

Async job-based shape (`submit_job`/`poll_job`), distinct from the synchronous `BaseProvider.generate_image`.
Polling realistically wants Phase 14's Celery infra.

### Phase 18 - One-prompt -> app

Generate -> execute (Phase 13's sandbox) -> capture error -> feed back -> repeat, hard iteration + cost cap
tied into Phase 4's usage tracking. Scope narrowed to something with a checkable success condition, not an
open-ended "build me an app."

## Cross-cutting

- Every phase extends `chat/tests.py`'s existing `TestCase` + `force_login`/`reverse()` pattern. External
  services (Groq/Mistral/Tavily/Docker/Gmail/video providers) are always mocked in tests, never hit for real
  in CI.
- `chat.html` (~3300 lines, no build step) gets its CSS/JS externalized in Phase 2, before more pages
  (profile, knowledge base, coding studio, analytics) each tempt another giant inline block.
- CI (`.github/workflows/ci.yml`) gains a Postgres service container from Phase 6 onward, and
  `CELERY_TASK_ALWAYS_EAGER=True` test settings from Phase 14 onward.
