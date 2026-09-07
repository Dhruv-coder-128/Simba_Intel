import os
import sys
import django
import json

sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'simba_web.settings')
django.setup()

from django.contrib.auth import get_user_model
from chat.models import (
    ChatSession, Message, UserProfile, UserFact, ConversationHighlight, SavedPrompt, ActivityEvent,
)
from chat.services.smart_router import route_with_reason
from chat.services.conversation_intelligence import _deterministic_title_fallback, suggest_followups
from chat.services.conversation_memory import (
    build_context_messages, _classify_fact_category, generate_session_summary,
)
from chat.views import _extract_prompt_variables

User = get_user_model()
user, _ = User.objects.get_or_create(username='test_phase4_user', defaults={'email': 'phase4@test.com'})
profile = UserProfile.get_or_create_for(user)

print("=== 1. TESTING SMART ROUTING MODES ===")
for mode in ['auto', 'fast', 'balanced', 'powerful', 'economical']:
    model, mode_name, reason = route_with_reason(mode, "def quicksort(arr):", False, profile.default_model)
    print(f"Mode [{mode.upper()}]: Resolved -> {model} (Mode={mode_name}, Reason={reason[:40]}...)")
    assert model is not None, f"Failed to resolve model for {mode}"

print("\n=== 2. TESTING SMART TITLE FALLBACK ===")
queries = [
    ("Can you please help me write a Django PostgreSQL connection pool manager?", "PostgreSQL Connection Pool Manager"),
    ("what is quantum computing entanglement?", "Quantum Computing Entanglement"),
    ("hello", "AI Workspace Session"),
]
for q, expected in queries:
    fallback = _deterministic_title_fallback(q)
    print(f"Query: '{q}' -> Fallback Title: '{fallback}'")
    assert len(fallback) > 0 and fallback != "New Chat", "Fallback title is invalid"

print("\n=== 3. TESTING PROMPT VARIABLES PARSER ===")
template = "Write a comprehensive {{language}} implementation of {{algorithm}} focusing on {{constraint}}."
vars_found = _extract_prompt_variables(template)
print(f"Template variables extracted: {vars_found}")
assert vars_found == ['language', 'algorithm', 'constraint'], f"Unexpected vars: {vars_found}"

# Create Prompt with Variables & Tags
prompt = SavedPrompt.objects.create(
    user=user,
    title="Algorithm Generator",
    content=template,
    category="Coding",
    tags="python,algorithms,cs",
    variables=vars_found,
)
print(f"SavedPrompt created: id={prompt.id}, tags={prompt.tags}, variables={prompt.variables}")

print("\n=== 4. TESTING CONVERSATION HIGHLIGHTS ===")
session = ChatSession.objects.create(user=user, title="Architecture Review Session")
highlight = ConversationHighlight.objects.create(
    user=user,
    session=session,
    highlight_type="decision",
    title="Adopt Redis Connection Pooling",
    content="Decided to use django-redis with MAX_CONNECTIONS=50 for optimal worker concurrency."
)
print(f"Highlight created: id={highlight.id}, type={highlight.highlight_type}, title={highlight.title}")
assert highlight.id is not None

print("\n=== 5. TESTING USER MEMORIES & CATEGORIES ===")
mem = UserFact.objects.create(
    user=user,
    fact="Prefers dark theme and strict TypeScript with no any types",
    category=_classify_fact_category("Prefers dark theme and strict TypeScript with no any types"),
    source_session=session
)
print(f"Memory created: id={mem.id}, category={mem.category}, fact='{mem.fact}'")
assert mem.category in ['preference', 'coding_style']

print("\n=== 6. TESTING HIERARCHICAL CONTEXT BUILDER ===")
# Enable memory
profile.memory_enabled = True
profile.save()

# Add turns and set active_leaf
msg_u = Message.objects.create(session=session, role='user', content='Hello Simba')
msg_a = Message.objects.create(session=session, role='assistant', content='Hello! How can I assist you today?', parent=msg_u)
session.active_leaf = msg_a
session.summary = "User initialized the workspace for architecture review."
session.save()

ctx_messages = build_context_messages(session, "Next step in planning", "You are SIMBA_INTEL AI OS.")
print(f"Hierarchical context message count: {len(ctx_messages)}")
for i, m in enumerate(ctx_messages):
    print(f"  [{i}] ({m['role']}): {m['content'][:60]}...")
assert len(ctx_messages) >= 4, f"Expected at least 4 messages (system, memory, user, assistant, query), got {len(ctx_messages)}"

print("\n=== 7. TESTING RECOVERY & CLEANUP ===")
# Cleanup test objects
highlight.delete()
prompt.delete()
mem.delete()
session.delete()
print("Cleaned up test objects.")

print("\n>>> ALL PHASE 4 VERIFICATION CHECKS PASSED SUCCESSFULLY! <<<")
