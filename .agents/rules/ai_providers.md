# AI & LLM Provider Integration Rules

This rule documents the multi-provider AI architecture of Simba Intel and establishes guidelines for AI-related development.

## Provider Architecture

```
User Query ──> views.ask_ai()
                     │
                     ▼
          chat.services.ai_router
          ├── Safety Prompt Injection (_inject_safety_instruction)
          ├── Rate-Limit & 429 Detection (is_rate_limit_error)
          ├── Provider Cooldown Cache (mark_provider_cooldown)
          └── Fallback Chain Resolution (get_fallback_chain)
                     │
                     ▼
          chat.services.provider_manager.get_provider()
                     │
     ┌───────────────┼───────────────┬───────────────┐
     ▼               ▼               ▼               ▼
GroqProvider   MistralProvider   VirtualProvider   OpenRouterProvider
(Nova Mind)       (SkyNet)         (Cyber Max)        (Ox Alpha)
```

## Core Principles

1. **Adhere to `BaseProvider` Interface**:
   - All AI integrations must subclass `BaseProvider` (`chat/providers/base.py`).
   - Must implement:
     - `chat(messages, model, **kwargs) -> str`
     - `chat_stream(messages, model, **kwargs) -> Generator[str, None, None]`
     - `vision(messages, model, **kwargs) -> str`
     - `generate_image(prompt, model, **kwargs) -> str`
   - Provider code must be isolated in `chat/providers/` and never leaked into views or templates.

2. **Model Registry & Fallback Chains**:
   - Every supported model must be registered in `MODEL_REGISTRY` (`chat/services/model_registry.py`) with a `ModelConfig` detailing capabilities (`supports_vision`, `supports_image_gen`, `context_window`, `min_role`).
   - Every text model should define a standby path in `FALLBACK_CHAINS` to gracefully survive single-provider outages or rate limits.
   - Provider identity must never be exposed to public UI: map raw provider strings to `PROVIDER_DISPLAY_NAMES` (e.g., `groq` -> "SkyNet Cloud", `mistral` -> "NovaMind Cloud").

3. **Routing & Safety Enforcement**:
   - All chat and vision requests must route through `chat.services.ai_router`.
   - Never call providers directly from views.
   - The safety instruction (`SAFETY_INSTRUCTION` in `ai_router.py`) must be injected into system messages to ensure professional, non-retaliatory behavior.

4. **Usage Tracking & Rate Limiting**:
   - Every AI operation (chat stream, vision call, image generation) must record a `UsageEvent` via `chat.services.usage.record_usage()`.
   - Sliding-window rate limiting is enforced via `check_rate_limit(user)` (30 requests/minute). Check this before dispatching expensive provider calls.
   - Daily usage caps from `UserProfile` must be respected unless `user.profile.unlimited_usage` is True.
   - Failed provider calls should record a failure (`record_failure`) so users are not penalized on quota for upstream outages.

5. **Secrets & Credentials**:
   - API keys (`GROQ_API_KEY`, `MISTRAL_API_KEY`, `TAVILY_API_KEY`, `OPENROUTER_API_KEY`) must be read exclusively from environment variables via `os.getenv()`.
   - If an API key is missing, providers must fail gracefully with descriptive error logging (`ErrorLog.record`) rather than crashing the application.
