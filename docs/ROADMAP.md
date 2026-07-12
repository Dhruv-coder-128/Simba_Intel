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

### Phase 3 - Message schema evolution

The current `ChatMessage` model is one row per user+assistant turn pair - it cannot represent branching
(two answers to one question) without hacks. Add a new `Message` model (role, content, `parent` self-FK,
`extra_data`) **alongside** the existing `ChatMessage` table (never touched/deleted - permanent rollback
copy). A one-time data migration walks existing sessions and reproduces today's linear history as a single
branch with no siblings. `chat_home` gets a small adapter that re-pairs the active-leaf chain into objects
exposing the same field names `chat.html`'s render loop already expects, so the template needs no changes for
the read path. `chat/services/memory.py:get_conversation_history` gets rewritten to walk the active-leaf
chain - every later context-injection feature (memory, knowledge base, fetched pages, research agent steps)
plugs in here.

### Phase 4 - Usage & cost tracking, rate limiting

New `UsageEvent` model (provider, model, tokens, estimated cost, latency). Both `groq_provider.py` and
`mistral_provider.py` are OpenAI-compatible and support `stream_options={"include_usage": True}` to get real
token counts from streaming responses - currently discarded. A static per-model cost table gives estimated
USD cost. Rate limiting is DB-backed (sliding window against `UsageEvent`) rather than pulling in a
Redis-based limiter prematurely - revisit once Phase 14 introduces Redis anyway.

### Phase 5 - Analytics dashboard

Pure read-side view over Phase 4's `UsageEvent` data - cost/token breakdown by model/provider/day. Use the
`dataviz` skill when actually building the charts.

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
