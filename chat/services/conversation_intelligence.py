"""Conversation Intelligence (Part 6) - AI-generated titles, on-demand
follow-up suggestions, and a lightweight "related conversations" heuristic.

Kept separate from conversation_memory.py on purpose: that module is about
*remembering* (summarizing/compressing/recalling), this one is about
*presenting* a conversation back to the user more usefully. They share the
same "best-effort, never break the caller" posture, and the same cheap
model (chat.services.conversation_memory.MEMORY_MODEL_ID) for the same
reason - short outputs from a short prompt, where the flagship model's
extra quality isn't worth its latency/cost.
"""
import logging
import re

from chat.services.ai_router import chat as ai_chat
from chat.services.conversation_memory import MEMORY_MODEL_ID
from chat.services.model_registry import get_fallback_chain

logger = logging.getLogger("simba_intel")

TITLE_SYSTEM_PROMPT = (
    "Generate a short, specific title (3-6 words, no quotes, no trailing "
    "punctuation) for a conversation that starts with the exchange below. "
    "Respond with the title only."
)

FOLLOWUP_SYSTEM_PROMPT = (
    "Suggest exactly 3 short follow-up questions or requests the user might "
    "naturally ask next, based on the reply below. One per line, no "
    "numbering, no quotes, each under 12 words."
)

# Generic titles the naive truncation fallback can produce - only these get
# upgraded, so a user who already renamed a chat by hand never has their
# choice silently overwritten.
_GENERIC_TITLE_PATTERN = re.compile(r"^(New Chat|Chat|Untitled|New Conversation|Attachment: .+)$", re.IGNORECASE)

_MARKDOWN_NOISE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_CHARS_RE = re.compile(r"[`*_#>]")

_FILLER_PREFIXES_RE = re.compile(
    r"^(can you please|could you please|please|can you|could you|help me with|how do i|how to|what is|tell me about|explain|write a|create a|generate a)\s+",
    re.IGNORECASE
)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "for",
    "and", "or", "with", "how", "what", "why", "do", "does", "can", "i", "my",
    "me", "you", "your", "it", "this", "that", "please", "help", "about",
}


def _deterministic_title_fallback(user_query: str) -> str:
    """Deterministic, high-quality title fallback for when AI generation fails.
    Strips polite filler, selects first 3-6 substantive words, and Title Cases."""
    clean = _MARKDOWN_NOISE_RE.sub(" ", user_query or "")
    clean = _MARKDOWN_CHARS_RE.sub(" ", clean)
    clean = _FILLER_PREFIXES_RE.sub("", clean.strip()).strip()
    words = [w.strip(" ,.-;:_!?\"'()") for w in clean.split() if w.strip(" ,.-;:_!?\"'()")]
    
    if not words:
        return "Intelligence Workspace Session"
    
    substantive = [w for w in words if w.lower() not in _STOPWORDS]
    selected = substantive[:5] if len(substantive) >= 2 else words[:5]
    
    title = " ".join(selected).title()
    return title[:60] if title else "AI Workspace Session"


def maybe_generate_smart_title(session, first_user_query, first_ai_response):
    """Sets a clean, substantive title for the session's first turn.
    Tries AI generation first, falling back to deterministic title synthesis.
    Never touches a user-renamed title."""
    current_title = (session.title or "").strip()
    is_generic = _GENERIC_TITLE_PATTERN.match(current_title) or not current_title or current_title == (first_user_query or "")[:30]
    
    if not is_generic:
        return

    title = None
    try:
        prompt = f"Generate a concise, descriptive 3-5 word title for a conversation that starts with: '{first_user_query[:100]}'. Reply with only the title."
        resp = ai_chat(MEMORY_MODEL_ID, [{"role": "user", "content": prompt}], max_tokens=15)
        clean = (resp or "").strip().strip('"\'')
        if clean and len(clean) >= 3 and len(clean) <= 60:
            title = clean
    except Exception:
        pass

    if not title:
        title = _deterministic_title_fallback(first_user_query)

    session.title = title
    session.save(update_fields=["title"])


def _dedupe_suggestions(raw: str) -> list:
    suggestions = [line.strip(" -*\t123456789.") for line in raw.splitlines() if line.strip(" -*\t123456789.")]
    seen = set()
    deduped = []
    for s in suggestions:
        key = s.lower()
        if key in seen or len(s) < 5:
            continue
        seen.add(key)
        deduped.append(s)
    return deduped[:4]


def _validate_suggestion(s: str, user_query: str, reply: str) -> bool:
    """Validates each suggestion against conversation topic constraints.
    Rejects suggestions that:
    - introduce unrelated topics (e.g. YouTube, calculate something when not asked)
    - assume information not discussed
    - reference code when no code exists
    - reference tests when no testing topic exists
    - reference files that were not discussed
    - repeat the exact same question
    - are generic filler
    """
    if not s or len(s) < 5 or len(s) > 120:
        return False

    s_lower = s.lower().strip()
    q_lower = (user_query or "").lower().strip()
    r_lower = (reply or "").lower().strip()
    context = f"{q_lower} {r_lower}"

    # Do not repeat user question
    if s_lower == q_lower or (len(q_lower) > 8 and s_lower in q_lower):
        return False

    # Reject generic filler
    filler_patterns = (
        "open youtube", "calculate something", "search the web", "summarize everything"
    )
    if any(f in s_lower for f in filler_patterns):
        return False

    # Reject testing references when no tests/code were discussed
    if any(t in s_lower for t in ("unit test", "test case", "pytest", "tests for this")):
        has_test_context = any(t in context for t in ("test", "pytest", "unittest", "bug", "error", "assert")) or "```" in reply or "def " in reply
        if not has_test_context:
            return False

    # Reject code references if no programming/code was discussed
    if any(c in s_lower for c in ("code example", "refactor", "line-by-line", "syntax")):
        has_code_context = any(c in context for c in ("code", "python", "javascript", "django", "function", "class", "def ", "var", "const", "html", "css", "sql", "algorithm", "recursion", "api")) or "```" in reply
        if not has_code_context:
            return False

    # Reject specific files if not discussed
    for ext_file in ("settings.py", "models.py", "views.py", "package.json", "dockerfile"):
        if ext_file in s_lower and ext_file not in context:
            return False

    return True


def _filter_and_validate_suggestions(suggestions: list, user_query: str, reply: str) -> list:
    valid = []
    seen = set()
    for s in suggestions:
        clean = s.strip(" -*\t123456789.\"")
        if clean.lower() in seen:
            continue
        if _validate_suggestion(clean, user_query, reply):
            seen.add(clean.lower())
            valid.append(clean)
            if len(valid) == 3:
                break
    return valid


def _derive_contextual_followups(user_query: str, reply: str) -> list:
    """Context-aware, domain-sensitive follow-up synthesis.
    Extracts the underlying intent and subject from both user query and assistant reply.
    Enforces:
    - Maximum 3 suggestions
    - Relevant, actionable, short (<12 words), natural
    - No generic filler ("Tell me more", "Open YouTube", "Summarize everything")
    - Non-repetitive
    """
    q_raw = (user_query or "").strip()
    r_raw = (reply or "").strip()

    q_lower = q_raw.lower()
    r_lower = r_raw.lower()
    combined = f"{q_lower} {r_lower}"

    # 1. 403 / CSRF / Login Form / Auth Errors (Example D)
    if any(k in combined for k in ("403", "forbidden", "csrf", "login form", "403 forbidden", "csrf verification failed")):
        return [
            "How do I configure the CSRF token in the form?",
            "Explain Django CSRF middleware settings",
            "How to check CSRF cookies and headers in browser tools",
        ]

    # 2. Recursion / Algorithms (Example E)
    if "recursion" in combined or "recursive" in combined:
        return [
            "Show the base case and recursive step breakdown",
            "How to avoid recursion depth limit errors",
            "Explain recursion vs iteration with an example",
        ]

    # 3. Weather / Environmental (Example F)
    if any(k in q_lower for k in ("weather", "temperature", "forecast", "is it raining")):
        return [
            "Check weather forecast for my city",
            "How do I connect a weather API or tool?",
        ]

    # 4. Django Models / ORM / Migrations (Example C)
    if any(k in q_lower for k in ("create a django model", "django model", "django models", "make a model in django", "how do i create a model in django")):
        return [
            "Show me a simple Django model example",
            "Explain Django migrations",
            "How do I query this model?",
        ]
    if "django" in q_lower or ("django" in r_lower and ("models.py" in r_lower or "views.py" in r_lower or "orm" in r_lower)):
        if any(k in combined for k in ("model", "orm", "database", "query", "migration", "filter")):
            return [
                "Show me a simple Django model example",
                "Explain Django migrations",
                "How do I query this model?",
            ]
        return [
            "Show Django view and URL configuration",
            "How to handle forms and validation in Django",
            "Explain Django authentication best practices",
        ]

    # 5. Casual / Conversational / Capabilities / Identity (Example A)
    is_casual = (
        any(q_lower.startswith(g) for g in ("hi", "hello", "hey", "sup", "greetings", "good morning", "good evening", "good afternoon")) or
        any(k in q_lower for k in ("what can you do", "who are you", "how are you", "what are your capabilities", "introduce yourself", "help me get started", "what can simba do"))
    )
    if is_casual:
        return [
            "What can you help me with?",
            "Tell me what you can do",
            "What desktop tasks can you automate?",
        ]

    # 6. Python Conceptual vs Python Code/Debug (Example B)
    if any(k in q_lower for k in ("what is python", "tell me about python", "learn python", "why use python", "what's python")) or q_lower == "python":
        return [
            "Show a simple Python code example",
            "What is Python commonly used for?",
            "How does Python compare to JavaScript?",
        ]

    # 7. BMI / Health & Nutrition Calculations
    if "bmi" in q_lower or "body mass index" in combined:
        return [
            "Show me an example calculation",
            "Explain BMI categories & ranges",
            "Calculate BMI for my height and weight",
        ]
    if any(k in q_lower for k in ("calorie", "diet", "workout", "protein", "heart rate", "exercise", "nutrition")):
        return [
            "What are the recommended daily targets?",
            "Show a practical routine or meal plan",
            "What common mistakes should I avoid?",
        ]

    # 8. Python Development & Debugging
    if "python" in q_lower or ("python" in r_lower and ("```python" in r_raw or "def " in r_raw)):
        if any(err in combined for err in ("error", "exception", "traceback", "debug", "failed", "bug")):
            return [
                "How do I fix this error in Python?",
                "Show Python unit tests for this",
                "Explain Python best practices to prevent this",
            ]
        return [
            "Show practical Python code examples",
            "Explain Python best practices & edge cases",
            "How to write unit tests for this in Python",
        ]

    # 9. General Code Debugging & Diagnostics
    is_debug = any(k in q_lower for k in ("debug", "error", "exception", "traceback", "syntaxerror", "typeerror", "valueerror", "fix", "bug", "failing", "broken", "issue in"))
    has_stack_trace = "traceback" in r_lower or "syntaxerror" in r_lower or "typeerror" in r_lower or "exception" in r_lower
    if is_debug or has_stack_trace:
        return [
            "Walk through the fix step-by-step",
            "Check for potential edge cases",
            "How to add error handling to prevent this",
        ]

    # 10. Simba Desktop Agent & System Automation
    if any(k in q_lower for k in ("agent", "automation", "automate", "desktop agent", "screen", "notepad", "calculator", "click", "browser", "control my pc")):
        return [
            "Walk through the next automated step",
            "Show tool parameters and options",
            "How to verify the automated execution outcome",
        ]

    # 11. Database / SQL
    if any(k in q_lower for k in ("sql", "postgres", "postgresql", "sqlite", "query", "select ", "table", "index", "schema")):
        return [
            "Show SQL query optimization tips",
            "How to handle indexing and performance",
            "Explain schema constraints and relationships",
        ]

    # 12. Web APIs & Backend
    if any(k in q_lower for k in ("api", "rest", "endpoint", "fastapi", "flask", "json", "post request", "get request")):
        return [
            "Show API request and response payload",
            "How to implement authentication for this API",
            "Explain error handling and status codes",
        ]

    # 13. Frontend / JavaScript / React / CSS
    if any(k in q_lower for k in ("javascript", "typescript", "react", "css", "html", "vue", "tailwind", "dom", "frontend")):
        return [
            "Show component code example",
            "How to handle state and re-renders",
            "Explain responsive styling and layout",
        ]

    # 14. Comparison Queries (X vs Y)
    if any(k in q_lower for k in (" vs ", " versus ", "difference between", "which is better", "compare ", "pros and cons")):
        return [
            "Compare performance and scalability trade-offs",
            "Which one is better for beginners?",
            "Show a comparison table of key features",
        ]

    # 15. Mathematics / Formulas / Calculations
    if any(k in q_lower for k in ("calculate", "formula", "percentage", "math", "tip", "interest", "equation")):
        return [
            "Show step-by-step formula breakdown",
            "Calculate with different example values",
            "Explain the mathematical assumptions",
        ]

    # 16. Code in Reply (General Programming)
    has_code = "```" in r_raw or any(k in r_lower for k in ("def ", "class ", "function", "import ", "const ", "let "))
    if has_code:
        return [
            "Walk through the code step-by-step",
            "How to write unit tests for this",
            "Check for potential edge cases",
        ]

    # 17. Multi-step How-To / Guides
    has_steps = any(marker in r_raw for marker in ("1.", "2.", "Step 1", "Phase 1", "- [ ]")) or "how to" in q_lower
    if has_steps:
        return [
            "Walk through the next implementation step",
            "What potential bottlenecks should we watch for?",
            "Summarize the prerequisites needed",
        ]

    # 18. Dynamic Concept Extraction ("What is X", "Explain X", "Tell me about X")
    clean_q = _MARKDOWN_NOISE_RE.sub(" ", q_raw)
    clean_q = _MARKDOWN_CHARS_RE.sub(" ", clean_q)
    clean_q = _FILLER_PREFIXES_RE.sub("", clean_q.strip()).strip()
    concept_words = [w.strip(" ,.-;:_!?\"'()") for w in clean_q.split() if w.strip(" ,.-;:_!?\"'()")]
    concept_words = [w for w in concept_words if w.lower() not in _STOPWORDS]

    if concept_words and len(concept_words) <= 4:
        concept = " ".join(concept_words).title()
        return [
            f"Explain practical use cases of {concept}",
            f"What are the pros and cons of {concept}?",
            f"Provide a real-world example of {concept}",
        ]

    # 19. Substantive Fallback
    return [
        "Provide a practical real-world example",
        "What are the key advantages and trade-offs?",
        "Can you explain this in simpler terms?",
    ]


def _derive_followups_from_reply(reply: str) -> list:
    """Fallback taking just reply for backwards compatibility with tests and callers."""
    return _derive_contextual_followups("", reply)


def suggest_followups(last_assistant_reply: str, user_query: str = "") -> list:
    """Fast, context-aware follow-up generation.
    Returns up to 3 short, actionable, natural follow-up suggestions derived
    from both the user's query and the assistant's reply.
    """
    reply = (last_assistant_reply or "").strip()
    query = (user_query or "").strip()

    if not reply:
        return []

    # If the reply represents an error, failure, or rate limit, do not force follow-ups.
    lower_reply = reply.lower()
    if any(err_marker in lower_reply for err_marker in (
        "something went wrong",
        "couldn't generate a response",
        "rate-limited",
        "connection notice",
        "request timed out",
        "communication with the server was interrupted",
        "server error:",
    )):
        return []

    # If ai_chat is mocked or available in candidates, attempt AI generation with strict contextual prompt
    prompt_context = f"User: {query}\nAssistant: {reply[:4000]}" if query else reply[:4000]
    messages = [
        {"role": "system", "content": (
            "Suggest up to 3 short follow-up questions the user might naturally ask next, "
            "strictly relevant to the conversation topic. One per line, no numbering, no quotes, "
            "each under 12 words. Do not suggest code or unit tests unless code was discussed."
        )},
        {"role": "user", "content": prompt_context},
    ]

    candidates = [MEMORY_MODEL_ID] + get_fallback_chain(MEMORY_MODEL_ID)
    for candidate in candidates[:2]:
        try:
            result = ai_chat(candidate, messages).strip()
            raw_suggestions = _dedupe_suggestions(result)
            validated = _filter_and_validate_suggestions(raw_suggestions, query, reply)
            if validated:
                return validated[:3]
        except Exception as e:
            logger.warning("Follow-up suggestion failed (model=%s): %s", candidate, e)
            continue

    # Fall back to high-quality contextual rule synthesis
    fallback = _derive_contextual_followups(query, reply)
    validated = _filter_and_validate_suggestions(fallback, query, reply)
    if validated:
        return validated[:3]
    return fallback[:3]


_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on", "for",
    "and", "or", "with", "how", "what", "why", "do", "does", "can", "i", "my",
    "me", "you", "your", "it", "this", "that", "please", "help", "about",
}


def _significant_words(text: str) -> set:
    words = re.findall(r"[a-zA-Z']{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def find_related_conversations(session, limit=5):
    """Deliberately not embeddings/vector-search based - there's no vector
    store in this project, and adding one just for this would be a lot of
    new infrastructure for a "related chats" list. Word-overlap between
    session titles is a cheap, dependency-free proxy that's good enough for
    surfacing a handful of plausibly-related past conversations."""
    from chat.models import ChatSession

    my_words = _significant_words(session.title)
    if not my_words:
        return []

    candidates = ChatSession.objects.filter(
        user=session.user, is_archived=False,
    ).exclude(id=session.id).only("id", "title")

    scored = []
    for candidate in candidates:
        overlap = my_words & _significant_words(candidate.title)
        if overlap:
            scored.append((len(overlap), candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored[:limit]]
