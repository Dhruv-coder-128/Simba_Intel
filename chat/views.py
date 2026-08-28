
import base64
import json
import os
import re
import time
import uuid
import zoneinfo
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse, JsonResponse, FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
import psutil

try:
    import GPUtil
    GPUtil_AVAILABLE = True
except ImportError:
    GPUtil_AVAILABLE = False

from chat.models import (
    ChatSession, Message, MessageAttachment, UserProfile, UsageEvent,
    RecoveryCode, Broadcast, UserSession, SecurityEvent, FeatureFlag,
)
from chat.services.ai_router import chat_stream_with_failover, vision as ai_vision
from chat.services.image_router import generate_image
from chat.services.memory import build_messages, messages_to_history_dicts, SYSTEM_PROMPT
from chat.services.conversation_memory import (
    build_context_messages, maybe_summarize_session, extract_and_store_facts, get_user_memory_context,
)
from chat.services.conversation_intelligence import (
    maybe_generate_smart_title, suggest_followups, find_related_conversations,
)
from chat.services.message_tree import (
    append_turn, build_display_messages, regenerate_assistant_reply, set_active_leaf, walk_chain_from,
)
from chat.services.message_stats import build_stats
from chat.services.model_registry import (
    MODEL_REGISTRY, list_available_models, get_model_config, is_model_allowed_for_user,
)
from chat.services.searxng import searxng_web_search, searxng_image_search
from chat.services.smart_router import resolve_model_id
from chat.services.usage import record_usage, record_failure, check_rate_limit, check_daily_limit
from chat.services.verification import is_email_verified, verification_required
from chat.utils.logger import SimbaLogger
from chat.utils.request_info import client_ip, raw_user_agent

from chat.file_analyzer import analyze_file
from chat.agent.controller import default_agent_controller
from chat.agent.fast_router import default_fast_router
from chat.agent_views import (
    agent_connect_view, agent_poll_view, agent_result_view,
    agent_heartbeat_view, agent_disconnect_view,
    agent_status_view, agent_regenerate_token_view,
)

# Loaded once at import time (not per-request) - the same sorted list backs
# both the Settings > General timezone <select> and server-side validation
# in profile_settings/set_timezone, so a submitted value can never diverge
# from what the dropdown actually offered.
AVAILABLE_TIMEZONES = sorted(zoneinfo.available_timezones())


logger = SimbaLogger()

User = get_user_model()

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf", ".csv", ".tsv", ".txt", ".md", ".json", ".xml", ".yaml", ".yml",
    ".log", ".env", ".sql", ".ini", ".cfg", ".conf", ".toml",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".sass",
    ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".cs", ".rs", ".go",
    ".php", ".rb", ".swift", ".kt", ".sh", ".bash", ".zsh", ".bat", ".ps1",
    ".doc", ".docx",
}
ALLOWED_UPLOAD_EXTENSIONS = ALLOWED_DOCUMENT_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS_PER_MESSAGE = 6

IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

MIME_TYPE_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".ts": "text/typescript",
    ".py": "text/x-python",
    ".java": "text/x-java-source",
    ".cpp": "text/x-c++src",
    ".c": "text/x-csrc",
    ".h": "text/x-chdr",
    ".rs": "text/x-rustsrc",
    ".go": "text/x-go",
    ".php": "text/x-php",
    ".rb": "text/x-ruby",
    ".sh": "application/x-sh",
    ".sql": "application/sql",
    ".md": "text/markdown",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".log": "text/plain",
    ".env": "text/plain",
}


def _get_file_type(ext: str) -> str:
    ext = ext.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".sass",
               ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".cs", ".rs", ".go",
               ".php", ".rb", ".swift", ".kt", ".sh", ".bash", ".zsh", ".bat", ".ps1", ".sql"}:
        return "code"
    if ext in {".txt", ".md", ".json", ".xml", ".yaml", ".yml", ".log", ".env", ".csv", ".tsv", ".ini", ".cfg", ".conf", ".toml"}:
        return "text"
    return "file"


def _validate_attachment(attachment):
    """Returns (safe_name, ext, error_message_or_None)."""
    if attachment.size > MAX_UPLOAD_SIZE_BYTES:
        return None, None, "File too large (max 10MB)"
    safe_name = os.path.basename(attachment.name)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return None, None, "Unsupported file type"
    return safe_name, ext, None


def _save_attachment_record(attachment, session, user, safe_name, ext):
    """Persists an uploaded attachment to a MessageAttachment database record and media storage."""
    file_type = _get_file_type(ext)
    mime = MIME_TYPE_MAP.get(ext, getattr(attachment, "content_type", "") or "application/octet-stream")
    record = MessageAttachment(
        session=session,
        user=user,
        original_name=safe_name,
        file_size=attachment.size,
        mime_type=mime,
        file_type=file_type,
    )
    record.file.save(safe_name, attachment, save=False)
    record.save()
    return record


def _extract_attachment_text(attachment_or_record, safe_name, ext):
    """Extract text from an uploaded file or persistent MessageAttachment."""
    if hasattr(attachment_or_record, "file") and hasattr(attachment_or_record.file, "path"):
        try:
            if os.path.exists(attachment_or_record.file.path):
                return analyze_file(attachment_or_record.file.path)
        except Exception:
            pass

    save_dir = os.path.join(settings.BASE_DIR, "uploads")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{uuid.uuid4().hex}{ext}")
    try:
        with open(save_path, "wb+") as f:
            if hasattr(attachment_or_record, "chunks"):
                for chunk in attachment_or_record.chunks():
                    f.write(chunk)
            elif hasattr(attachment_or_record, "file"):
                attachment_or_record.file.seek(0)
                f.write(attachment_or_record.file.read())
        return analyze_file(save_path)
    finally:
        try:
            if os.path.exists(save_path):
                os.remove(save_path)
        except OSError:
            pass


def _get_tavily_search(query: str):
    try:
        from tavily import TavilyClient
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            return None
        client = TavilyClient(api_key=tavily_api_key)
        response = client.search(query=query, search_depth="advanced", max_results=5)
        return response.get("results", [])
    except Exception as e:
        logger.log_request(
            provider="tavily",
            latency=0,
            prompt_length=len(query),
            response_length=0,
            error=str(e)
        )
        return None


def _get_web_search_results(query: str):
    """SearXNG (chat/services/searxng.py) is the primary web search engine -
    self-hosted, cached, no per-request vendor cost. Falls back to Tavily
    only if SEARXNG_URL isn't configured or SearXNG returned nothing, so an
    existing Tavily-only deployment keeps working unmodified."""
    results = searxng_web_search(query)
    if results:
        return results
    return _get_tavily_search(query)


_MD_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]*)\)')


def _rewrite_images_in_stream(pairs):
    """Wraps a _stream_with_failover token_gen ((text, is_notice) pairs) and
    replaces every markdown image the model emits - ![alt](url) - with a
    real SearXNG image result for `alt` before it ever reaches the client,
    so a hallucinated/random/mismatched image URL is never shown (see
    chat/services/searxng.py's searxng_image_search). No real match found
    (no SEARXNG_URL configured, empty alt text, or nothing returned) means
    the image is dropped entirely - never left pointing at a broken or
    unrelated one.

    Only wraps search-augmented replies (see ask_ai) - buffers at most one
    in-progress, not-yet-closed image marker at a time, so ordinary text is
    never delayed; only the (rare, short) span of an actual image marker
    waits on one cached SearXNG lookup.
    """
    buffer = ""
    resolved_cache = {}

    def resolve(alt: str) -> str:
        alt = alt.strip()
        if not alt:
            return ""
        key = alt.lower()
        if key not in resolved_cache:
            resolved_cache[key] = searxng_image_search(alt)
        return resolved_cache[key]

    for token, is_notice in pairs:
        if is_notice:
            yield token, is_notice
            continue

        buffer += token
        out = []
        last_end = 0
        for m in _MD_IMAGE_RE.finditer(buffer):
            out.append(buffer[last_end:m.start()])
            real_url = resolve(m.group(1))
            if real_url:
                out.append(f"![{m.group(1)}]({real_url})")
            last_end = m.end()

        tail = buffer[last_end:]
        open_marker = tail.rfind("![")
        if open_marker == -1 and tail.endswith("!"):
            open_marker = len(tail) - 1
        if open_marker != -1 and ")" not in tail[open_marker:]:
            # An image marker may be starting here but hasn't closed yet -
            # hold it back, flush everything before it.
            if open_marker > 0:
                out.append(tail[:open_marker])
            buffer = tail[open_marker:]
        else:
            out.append(tail)
            buffer = ""

        if out:
            yield "".join(out), False

    if buffer:
        yield buffer, False


def _is_search_query(query: str) -> bool:
    search_keywords = ["latest", "today", "news", "search", "current", "price", "weather", "now", "recent", "stock", "market"]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in search_keywords)


def _stream_with_failover(model_id, messages, on_usage):
    """Shared by every stream_generator (ask_ai, regenerate_message,
    edit_message, continue_message) - wraps chat_stream_with_failover and
    tracks which model actually ends up serving the request. Returns
    (token_generator, serving, resolved) - both dicts are only reliable once
    the generator has been fully consumed.

    serving['model_id'] flips the moment a cross-model switch happens (see
    chat_stream_with_failover's on_switch contract) - always before the
    first token is yielded.

    resolved is populated by on_model_resolved, which only virtual/nvidia
    (pooled) providers ever call (see those providers' chat_stream) - it
    reports the real underlying model actually used within that pool/chain,
    since serving['model_id'] alone only ever holds a *visible* SIMBA model
    id (e.g. "quantum-core"), never the real provider model id. Empty for
    any other provider; callers fall back to get_model_config(serving[
    'model_id']).actual_model in that case, which is already the real model.

    token_generator yields (text, is_notice) pairs rather than plain
    strings: the switch notice must reach the live stream (so the user sees
    it) but must NEVER be folded into the caller's full_response
    accumulator, or it would get permanently saved into Message.content and
    reappear every time that reply is reloaded. Every call site's loop is
    `if not is_notice: full_response += text` before `yield text`.

    Pulled into one place rather than repeated inline at all four call
    sites: they're identical, and a copy-pasted mismatch between the
    `on_switch` closure and the variable it updates is exactly the kind of
    bug that's easy to introduce once and much harder to notice later."""
    serving = {"model_id": model_id}
    resolved = {}

    def on_switch(new_model_id):
        serving["model_id"] = new_model_id

    def on_model_resolved(info):
        resolved.update(info)

    def token_generator():
        for i, token in enumerate(chat_stream_with_failover(
            model_id, messages, on_switch=on_switch, on_usage=on_usage,
            on_model_resolved=on_model_resolved,
        )):
            if i == 0 and serving["model_id"] != model_id:
                switched_cfg = get_model_config(serving["model_id"])
                yield (f"_(Switched to {switched_cfg.display_name} after a temporary provider issue)_\n\n", True)
            yield (token, False)

    return token_generator(), serving, resolved


def _compute_folders_for_user(user):
    """Folders shown in the sidebar = the union of (a) folder names actually
    in use by a non-archived chat and (b) empty folders that only exist as a
    metadata row (created but nothing filed yet). Each carries its colour
    (from the Folder metadata row, default '' when none) and a live chat
    count. Shared by chat_home (initial render) and folders_summary (the
    no-reload refresh point JS calls after any folder-affecting action) so
    the two can never drift apart."""
    from chat.models import Folder as FolderModel
    from django.db.models import Count as _Count

    used_counts = dict(
        ChatSession.objects.filter(user=user, is_archived=False)
        .exclude(folder='').values_list('folder').annotate(n=_Count('id'))
    )
    folder_colors = dict(
        FolderModel.objects.filter(user=user).values_list('name', 'color')
    )
    folder_names = sorted(set(used_counts) | set(folder_colors), key=str.lower)
    return [
        {'name': name, 'color': folder_colors.get(name, ''), 'count': used_counts.get(name, 0)}
        for name in folder_names
    ]


@login_required
def chat_home(request):
    profile = UserProfile.get_or_create_for(request.user)

    view_mode = request.GET.get('view', 'active')
    folder_filter = request.GET.get('folder', '').strip()

    base_qs = ChatSession.objects.filter(user=request.user, is_archived=(view_mode == 'archived'))
    if folder_filter:
        base_qs = base_qs.filter(folder=folder_filter)
    sessions = list(base_qs.order_by('-is_pinned', '-id'))

    pinned_sessions = [s for s in sessions if s.is_pinned]
    favorite_sessions = [s for s in sessions if s.is_favorite and not s.is_pinned]
    other_sessions = [s for s in sessions if not s.is_pinned and not s.is_favorite]

    folders = _compute_folders_for_user(request.user)

    session_id = request.GET.get('session')
    messages = []
    current_session = None
    if session_id and session_id not in ["null", "None", ""]:
        try:
            current_session = get_object_or_404(ChatSession, id=session_id, user=request.user)
            messages = build_display_messages(current_session)
        except Exception:
            current_session = None

    if current_session:
        selected_model = request.session.get(f"session_model_{current_session.id}", request.session.get("selected_model", profile.default_model))
    else:
        # Genuinely new session: default to Ox Alpha (profile.default_model)
        selected_model = profile.default_model
        request.session["selected_model"] = selected_model

    models = list_available_models()
    # `active=True` alone isn't "currently showing" - starts_at/ends_at can
    # still make it scheduled-for-later or expired; there's normally at most
    # one active=True row (the admin console enforces that on create), so
    # checking status in Python here is one cheap row, not a query per user.
    active_broadcast = next(
        (b for b in Broadcast.objects.filter(active=True).order_by('-created_at') if b.is_currently_visible()),
        None,
    )
    return render(request, 'chat.html', {
        'sessions': sessions,
        'pinned_sessions': pinned_sessions,
        'favorite_sessions': favorite_sessions,
        'other_sessions': other_sessions,
        'folders': folders,
        'view_mode': view_mode,
        'folder_filter': folder_filter,
        'messages': messages,
        'current_session': current_session,
        'selected_model': selected_model,
        'models': models,
        'profile': profile,
        'email_verified': is_email_verified(request.user),
        'verification_required': verification_required(),
        'active_broadcast': active_broadcast,
    })


@login_required
def profile_settings(request):
    profile = UserProfile.get_or_create_for(request.user)
    valid_model_ids = {m['id'] for m in list_available_models()}
    valid_themes = {choice[0] for choice in UserProfile.THEME_CHOICES}
    verified = is_email_verified(request.user)

    if request.method == "POST":
        if not verified:
            return render(request, 'profile.html', {
                'profile': profile,
                'models': list_available_models(),
                'theme_choices': UserProfile.THEME_CHOICES,
                'timezone_choices': AVAILABLE_TIMEZONES,
                'accent_choices': UserProfile.ACCENT_OVERRIDE_CHOICES,
                'density_choices': UserProfile.DENSITY_CHOICES,
                'card_radius_choices': UserProfile.CARD_RADIUS_CHOICES,
                'animation_choices': UserProfile.ANIMATION_LEVEL_CHOICES,
                'glass_choices': UserProfile.GLASS_INTENSITY_CHOICES,
                'email_verified': False,
            }, status=403)
        display_name = request.POST.get('display_name', '').strip()[:100]
        default_model = request.POST.get('default_model', '').strip()
        theme = request.POST.get('theme', '').strip()
        timezone_name = request.POST.get('timezone', '').strip()

        profile.display_name = display_name
        if default_model in valid_model_ids:
            profile.default_model = default_model
        if theme in valid_themes:
            profile.theme = theme
        if timezone_name in AVAILABLE_TIMEZONES and timezone_name != profile.timezone:
            profile.timezone = timezone_name
            # An explicit pick from this form always wins from now on - stop
            # letting the JS auto-detect on chat.html silently override it.
            profile.timezone_auto = False
        profile.memory_enabled = request.POST.get('memory_enabled') == 'on'
        profile.notifications_enabled = request.POST.get('notifications_enabled') == 'on'

        # --- Appearance (Part 6) ---
        accent_override = request.POST.get('accent_override', '').strip()
        if accent_override in {c for c, _ in UserProfile.ACCENT_OVERRIDE_CHOICES}:
            profile.accent_override = accent_override
        density = request.POST.get('density', '').strip()
        if density in {c for c, _ in UserProfile.DENSITY_CHOICES}:
            profile.density = density
        card_radius = request.POST.get('card_radius', '').strip()
        if card_radius in {c for c, _ in UserProfile.CARD_RADIUS_CHOICES}:
            profile.card_radius = card_radius
        animation_level = request.POST.get('animation_level', '').strip()
        if animation_level in {c for c, _ in UserProfile.ANIMATION_LEVEL_CHOICES}:
            profile.animation_level = animation_level
        glass_intensity = request.POST.get('glass_intensity', '').strip()
        if glass_intensity in {c for c, _ in UserProfile.GLASS_INTENSITY_CHOICES}:
            profile.glass_intensity = glass_intensity

        profile.save()
        # Saving returns to the conversation the user was on before opening
        # Settings (restored client-side from sessionStorage into this hidden
        # field) rather than reloading the settings page itself - ownership
        # of next_session_id is re-checked by chat_home the same way any
        # ?session= link is, so an invalid/foreign id just falls back to no
        # session selected rather than ever leaking another user's chat.
        next_session_id = request.POST.get('next_session_id', '').strip()
        if next_session_id:
            return redirect(f'/?session={next_session_id}&saved=1')
        return redirect('/?saved=1')

    from allauth.socialaccount.models import SocialAccount
    from chat.models import UserFact

    return render(request, 'profile.html', {
        'profile': profile,
        'models': list_available_models(),
        'theme_choices': UserProfile.THEME_CHOICES,
        'timezone_choices': AVAILABLE_TIMEZONES,
        'accent_choices': UserProfile.ACCENT_OVERRIDE_CHOICES,
        'density_choices': UserProfile.DENSITY_CHOICES,
        'card_radius_choices': UserProfile.CARD_RADIUS_CHOICES,
        'animation_choices': UserProfile.ANIMATION_LEVEL_CHOICES,
        'glass_choices': UserProfile.GLASS_INTENSITY_CHOICES,
        'email_verified': verified,
        'user_sessions': UserSession.objects.filter(user=request.user).order_by('-created_at'),
        'current_session_key': request.session.session_key,
        'recent_logins': SecurityEvent.objects.filter(user=request.user, event_type='login').order_by('-created_at')[:10],
        'google_account': SocialAccount.objects.filter(user=request.user, provider='google').first(),
        'memory_fact_count': UserFact.objects.filter(user=request.user).count(),
        'conversation_count': ChatSession.objects.filter(user=request.user).count(),
    })


@login_required
def set_timezone(request):
    """Called once per page load by chat.html's auto-detect script with the
    browser's IANA zone (Intl.DateTimeFormat().resolvedOptions().timeZone).
    Only takes effect while profile.timezone_auto is still True - an explicit
    choice saved from Settings > General always wins from then on. Silently
    ignores an unrecognized name rather than erroring, since a browser can in
    principle report anything."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    tzname = request.POST.get('timezone', '').strip()
    if tzname not in AVAILABLE_TIMEZONES:
        return JsonResponse({"status": "ignored"})
    profile = UserProfile.get_or_create_for(request.user)
    if profile.timezone_auto and profile.timezone != tzname:
        profile.timezone = tzname
        profile.save(update_fields=['timezone'])
    return JsonResponse({"status": "ok", "timezone": profile.timezone})


@login_required
def logout_session(request, session_id):
    """Ends one of the user's own OTHER sessions (a specific device/browser)
    - looked up via UserSession rather than decoding the whole live Session
    table, since this only ever needs one user's own sessions, which is
    exactly what UserSession's user+session_key already index."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    user_session = get_object_or_404(UserSession, id=session_id, user=request.user)
    from django.contrib.sessions.models import Session
    Session.objects.filter(session_key=user_session.session_key).delete()
    user_session.delete()
    return JsonResponse({"status": "success"})


@login_required
def logout_all_sessions(request):
    """Ends every session for this user, including the one making this
    request - matching the literal "logout all sessions" ask (a separate,
    narrower "logout this device" is what the single-session button above
    already covers). The current request still completes normally since its
    session data is already loaded in memory; the next request from this
    browser will be anonymous, same as any other logged-out session."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from django.contrib.sessions.models import Session
    session_keys = list(UserSession.objects.filter(user=request.user).values_list('session_key', flat=True))
    Session.objects.filter(session_key__in=session_keys).delete()
    UserSession.objects.filter(user=request.user).delete()
    return JsonResponse({"status": "success"})


@login_required
def clear_memory(request):
    """Memory controls (Part 2) - deletes every UserFact this account has
    accumulated. Does NOT touch per-session summaries (ChatSession.summary):
    those are a within-conversation compression detail of one specific
    chat, not "memory" in the cross-chat-recall sense this control is
    about, and deleting them would just make that one conversation's own
    context worse for no privacy benefit."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import UserFact
    count, _ = UserFact.objects.filter(user=request.user).delete()
    return JsonResponse({"status": "success", "deleted": count})


@login_required
def analytics_dashboard(request):
    """Phase 5 (expanded): pure read-side view over UsageEvent - no writes
    happen here, so it's safe to hit as often as the user likes.

    Deliberately does NOT report a top-prompts list or a "files processed"
    count - neither is tracked anywhere in the data model today (no prompt
    text or file-processing event is stored), so faking them would mean
    showing invented numbers. Success/error rate (Part 7) IS real: every AI
    call site now records a failed UsageEvent (success=False, see
    usage.record_failure) alongside the pre-existing successful ones, so it
    reflects actual outcomes rather than being unavailable.

    `events` below is scoped to success=True and drives every pre-existing
    metric (totals, by-model/provider breakdowns, trends) completely
    unchanged from before this field existed - `all_events` (unfiltered) is
    only used for the new success/error rate figures, so a failed call
    can't quietly skew a cost/latency/volume number that's supposed to
    reflect real, completed usage.
    """
    if not FeatureFlag.is_enabled('analytics', default=True):
        messages.info(request, "Analytics is temporarily disabled by the administrator.")
        return redirect('home')

    import json
    from collections import defaultdict
    from datetime import timedelta

    from django.db.models import Count, Sum, Avg, F
    from django.db.models.functions import TruncDate, TruncMonth
    from django.utils import timezone

    from chat.services.model_registry import MODEL_REGISTRY, provider_display_name

    profile = UserProfile.get_or_create_for(request.user)

    all_events = UsageEvent.objects.filter(user=request.user)
    events = all_events.filter(success=True)
    total_attempts = all_events.count()
    successful_attempts = events.count()
    failed_attempts = total_attempts - successful_attempts
    success_rate = round(100 * successful_attempts / total_attempts, 1) if total_attempts else 100.0
    error_rate = round(100 - success_rate, 1) if total_attempts else 0.0

    totals = events.aggregate(
        total_requests=Count('id'),
        total_tokens=Sum(F('prompt_tokens') + F('completion_tokens')),
        total_cost=Sum('estimated_cost_usd'),
        avg_latency=Avg('latency'),
    )

    by_model_qs = (
        events.values('model_id', 'provider')
        .annotate(
            requests=Count('id'),
            tokens=Sum(F('prompt_tokens') + F('completion_tokens')),
            cost=Sum('estimated_cost_usd'),
        )
        .order_by('-requests')
    )
    by_model = []
    for row in by_model_qs:
        config = MODEL_REGISTRY.get(row['model_id'])
        by_model.append({
            'model_id': row['model_id'],
            'display_name': config.display_name if config else row['model_id'],
            # Never the raw provider string on this user-facing page - see
            # provider_display_name()'s docstring for why.
            'provider': provider_display_name(row['provider']),
            'requests': row['requests'],
            'tokens': row['tokens'] or 0,
            'cost': float(row['cost'] or 0),
        })

    by_provider = [
        {
            'provider': provider_display_name(row['provider']),
            'requests': row['requests'],
            'cost': float(row['cost'] or 0),
            'avg_latency': round(row['avg_latency'], 2) if row['avg_latency'] else 0,
        }
        for row in events.values('provider').annotate(
            requests=Count('id'), cost=Sum('estimated_cost_usd'), avg_latency=Avg('latency'),
        ).order_by('-requests')
    ]

    by_event_type = [
        {'event_type': row['event_type'], 'requests': row['requests'], 'cost': float(row['cost'] or 0)}
        for row in events.values('event_type').annotate(
            requests=Count('id'), cost=Sum('estimated_cost_usd')
        ).order_by('-requests')
    ]
    event_type_counts = {row['event_type']: row['requests'] for row in by_event_type}

    today = timezone.localdate()
    now = timezone.now()

    cutoff14 = now - timedelta(days=13)
    daily_qs = (
        events.filter(created_at__gte=cutoff14)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(requests=Count('id'), cost=Sum('estimated_cost_usd'), avg_latency=Avg('latency'),
                  tokens=Sum(F('prompt_tokens') + F('completion_tokens')))
        .order_by('day')
    )
    daily_by_date = {row['day'].isoformat(): row for row in daily_qs}
    daily_series = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        key = day.isoformat()
        row = daily_by_date.get(key)
        daily_series.append({
            'date': key,
            'requests': row['requests'] if row else 0,
            'cost': float(row['cost']) if row and row['cost'] else 0.0,
            'tokens': row['tokens'] if row and row['tokens'] else 0,
            'avg_latency': round(row['avg_latency'], 2) if row and row['avg_latency'] else 0,
        })

    # Model usage per day (last 14 days), for a stacked bar - top 5 models
    # by total volume get their own series, everything else folds into "Other"
    # so the chart doesn't get unreadable with a long tail of one-off models.
    top_model_ids = [m['model_id'] for m in by_model[:5]]
    model_daily_qs = (
        events.filter(created_at__gte=cutoff14)
        .annotate(day=TruncDate('created_at'))
        .values('day', 'model_id')
        .annotate(requests=Count('id'))
    )
    model_daily_map = defaultdict(lambda: defaultdict(int))
    has_other_models = False
    for row in model_daily_qs:
        if row['model_id'] in top_model_ids:
            key = row['model_id']
        else:
            key = 'Other'
            has_other_models = True
        model_daily_map[row['day'].isoformat()][key] += row['requests']
    model_stack_labels = top_model_ids + (['Other'] if has_other_models else [])
    model_stack_series = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        key = day.isoformat()
        row = model_daily_map.get(key, {})
        model_stack_series.append({'date': key, **{m: row.get(m, 0) for m in model_stack_labels}})

    # Weekly rollup (last 8 rolling 7-day windows) and monthly rollup (last 6
    # months) - computed from the same 14-day query would be wrong, so these
    # cover their own wider windows. Rolling weeks aren't calendar-aligned
    # (they're anchored to "today", not Monday), so they can't use a
    # TruncWeek aggregate - instead, one raw-timestamp fetch for the whole
    # 8-week span replaces what used to be 8 separate .count() queries.
    week_window_start = today - timedelta(days=7 * 8 - 1)
    weekly_dates = [
        timezone.localtime(ts).date()
        for ts in events.filter(created_at__date__gte=week_window_start).values_list('created_at', flat=True)
    ]
    weekly_series = []
    for i in range(7, -1, -1):
        week_end = today - timedelta(days=7 * i)
        week_start = week_end - timedelta(days=6)
        count = sum(1 for d in weekly_dates if week_start <= d <= week_end)
        weekly_series.append({'label': week_start.strftime('%b %d'), 'requests': count})

    # Monthly buckets ARE calendar-aligned (year/month), so TruncMonth can
    # replace what used to be 6 separate .count() queries with one grouped
    # query - bounded to the same ~6-month window rather than scanning the
    # user's entire history.
    monthly_window_start = now - timedelta(days=186)
    monthly_qs = (
        events.filter(created_at__gte=monthly_window_start)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(requests=Count('id'))
    )
    monthly_by_key = {row['month'].strftime('%Y-%m'): row['requests'] for row in monthly_qs if row['month']}
    monthly_series = []
    for i in range(5, -1, -1):
        # Compute the i-th month back from the current month, robust across
        # year boundaries without pulling in a calendar-arithmetic library.
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        key = f'{year}-{month:02d}'
        monthly_series.append({'label': key, 'requests': monthly_by_key.get(key, 0)})

    # Hour-of-day x day-of-week heatmap and a latency histogram - both need
    # per-row timestamps/latencies, so pull the (small) raw pairs once rather
    # than running 168 separate grouped queries.
    raw_pairs = list(events.values_list('created_at', 'latency'))
    heatmap_counts = defaultdict(int)
    latency_buckets = [0, 0, 0, 0, 0]  # <1s, 1-2s, 2-3s, 3-5s, 5s+
    for created_at, latency in raw_pairs:
        local_dt = timezone.localtime(created_at)
        heatmap_counts[(local_dt.weekday(), local_dt.hour)] += 1
        if latency is None:
            continue
        elif latency < 1:
            latency_buckets[0] += 1
        elif latency < 2:
            latency_buckets[1] += 1
        elif latency < 3:
            latency_buckets[2] += 1
        elif latency < 5:
            latency_buckets[3] += 1
        else:
            latency_buckets[4] += 1
    heatmap_data = [
        {'day': d, 'hour': h, 'count': c} for (d, h), c in heatmap_counts.items()
    ]

    recent_events = events.select_related('session').order_by('-created_at')[:20]

    # Trend indicators (Part 6) - period-over-period % change, computed from
    # the same `events` queryset rather than a second round-trip through
    # daily_series (which only covers 14 days and wouldn't cover the "this
    # month vs last month" comparison). None means "no prior-period activity
    # to compare against" (rendered as "New" rather than a misleading 0% or
    # divide-by-zero figure).
    def pct_change(current, previous):
        if not previous:
            return None if not current else 100
        return round(((current - previous) / previous) * 100)

    requests_today = events.filter(created_at__date=today).count()
    requests_yesterday = events.filter(created_at__date=today - timedelta(days=1)).count()
    requests_this_week = events.filter(created_at__date__gte=today - timedelta(days=6)).count()
    requests_last_week = events.filter(
        created_at__date__gte=today - timedelta(days=13), created_at__date__lt=today - timedelta(days=6),
    ).count()
    requests_this_month = events.filter(created_at__year=today.year, created_at__month=today.month).count()
    last_month_end = today.replace(day=1) - timedelta(days=1)
    requests_last_month = events.filter(
        created_at__year=last_month_end.year, created_at__month=last_month_end.month,
    ).count()

    # Top conversations by volume - genuinely derivable (UsageEvent already
    # links to session), unlike success/error rate or a prompts list above.
    top_conversations = [
        {
            'session_id': row['session'],
            'title': row['session__title'],
            'requests': row['requests'],
            'cost': float(row['cost'] or 0),
        }
        for row in events.exclude(session__isnull=True).values('session', 'session__title')
        .annotate(requests=Count('id'), cost=Sum('estimated_cost_usd'))
        .order_by('-requests')[:8]
    ]

    context = {
        'profile': profile,
        'total_requests': totals['total_requests'] or 0,
        'total_tokens': totals['total_tokens'] or 0,
        'total_cost': float(totals['total_cost'] or 0),
        'avg_latency': round(totals['avg_latency'], 2) if totals['avg_latency'] else 0,
        'active_models': len(by_model),
        'images_generated': event_type_counts.get('image', 0),
        'vision_calls': event_type_counts.get('vision', 0),
        'chat_messages': event_type_counts.get('chat', 0),
        'requests_today': requests_today,
        'requests_this_week': requests_this_week,
        'requests_this_month': requests_this_month,
        'requests_today_change': pct_change(requests_today, requests_yesterday),
        'requests_week_change': pct_change(requests_this_week, requests_last_week),
        'requests_month_change': pct_change(requests_this_month, requests_last_month),
        'top_conversations': top_conversations,
        'by_model': by_model,
        'by_provider': by_provider,
        'by_event_type': by_event_type,
        'daily_series': daily_series,
        'daily_series_json': json.dumps(daily_series),
        'by_event_type_json': json.dumps(by_event_type),
        'by_provider_json': json.dumps(by_provider),
        'model_stack_labels_json': json.dumps(model_stack_labels),
        'model_stack_series_json': json.dumps(model_stack_series),
        'weekly_series_json': json.dumps(weekly_series),
        'monthly_series_json': json.dumps(monthly_series),
        'heatmap_data_json': json.dumps(heatmap_data),
        'latency_buckets_json': json.dumps(latency_buckets),
        'recent_events': recent_events,
        'has_estimated_tokens': events.filter(tokens_are_estimated=True).exists(),
        'success_rate': success_rate,
        'error_rate': error_rate,
        'total_attempts': total_attempts,
        'failed_attempts': failed_attempts,
    }
    return render(request, 'analytics.html', context)


@login_required
def ask_ai(request):
    if request.method == "POST":
        if not check_rate_limit(request.user):
            return JsonResponse(
                {"type": "error", "message": "You're sending requests too quickly. Please wait a moment and try again."},
                status=429
            )
        profile = UserProfile.get_or_create_for(request.user)
        model_id = request.POST.get('model_id') or profile.default_model
        session_id = request.POST.get('session_id')
        attachments = request.FILES.getlist('attachment')
        # Session remembers the literal "auto" choice (so Auto mode stays
        # selected across reloads, re-routing fresh on every future message)
        # - model_id itself gets resolved to a concrete, real model right
        # below, so every line after this block can keep treating it as one
        # exactly like before Smart Routing existed.
        request.session["selected_model"] = model_id
        if session_id and session_id not in ["null", "None", ""]:
            request.session[f"session_model_{session_id}"] = model_id
        request.session.modified = True
        user_query = request.POST.get('query', '').strip()
        if model_id.lower() == "auto":
            has_image_attachment = any(
                os.path.splitext(att.name)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
                for att in attachments
            )
            model_id = resolve_model_id(model_id, user_query, has_image_attachment, profile.default_model)
        if not user_query and not attachments:
            return JsonResponse({"response": "Query cannot be empty"}, status=400)
        if len(attachments) > MAX_ATTACHMENTS_PER_MESSAGE:
            return JsonResponse(
                {"type": "error", "message": f"Too many attachments (max {MAX_ATTACHMENTS_PER_MESSAGE})"},
                status=400
            )
        try:
            first_name = attachments[0].name[:20] if attachments else ""
            session_title = user_query[:30] if user_query else (
                f"Attachment: {first_name}" if attachments else "New Chat"
            )
            if not session_id or session_id in ["null", "None", ""]:
                # A brand-new chat started while a folder is the active sidebar
                # filter must be filed into that folder immediately - leaving
                # this blank was the folder bug: the chat would render inside
                # the folder optimistically (client-side, from the currently-
                # filtered view) but revert to unfiled on the next real page
                # load, since the DB row itself never got a folder value.
                # Never applied to an existing session (the `else` branch
                # below) - continuing a chat must never silently refile it
                # just because the sidebar happens to be showing a different
                # folder right now.
                active_folder = request.POST.get('folder', '').strip()[:100]
                session = ChatSession.objects.create(user=request.user, title=session_title, folder=active_folder)
            else:
                session = ChatSession.objects.get(id=session_id, user=request.user)

            model_config = get_model_config(model_id)

            if not is_model_allowed_for_user(model_id, request.user):
                access_response = JsonResponse({
                    "type": "error",
                    "message": "Your account doesn't have access to this model.",
                })
                access_response["X-Session-ID"] = str(session.id)
                return access_response

            if attachments and not FeatureFlag.is_enabled('file_upload', default=True):
                upload_disabled_response = JsonResponse({
                    "type": "error",
                    "message": "File uploads are temporarily disabled by the administrator.",
                })
                upload_disabled_response["X-Session-ID"] = str(session.id)
                return upload_disabled_response

            saved_attachments = []
            if attachments:
                validated = []  # list of (attachment, safe_name, ext)
                for att in attachments:
                    safe_name, ext, attach_error = _validate_attachment(att)
                    if attach_error:
                        attach_response = JsonResponse(
                            {"type": "error", "message": f"{att.name}: {attach_error}"}, status=400
                        )
                        attach_response["X-Session-ID"] = str(session.id)
                        return attach_response
                    validated.append((att, safe_name, ext))

                for att, safe_name, ext in validated:
                    record = _save_attachment_record(att, session, request.user, safe_name, ext)
                    saved_attachments.append(record)

                image_files = [v for v in validated if v[2] in ALLOWED_IMAGE_EXTENSIONS]
                doc_files = [v for v in validated if v[2] not in ALLOWED_IMAGE_EXTENSIONS]

                if image_files and model_config.supports_vision and not is_email_verified(request.user):
                    verify_response = JsonResponse({
                        "type": "error",
                        "message": "Please verify your email to use Vision.",
                        "requires_verification": True,
                    })
                    verify_response["X-Session-ID"] = str(session.id)
                    return verify_response

                if image_files and model_config.supports_vision:
                    if not FeatureFlag.is_enabled('vision', default=True):
                        disabled_response = JsonResponse(
                            {"type": "error", "message": "Vision is temporarily disabled by the administrator."}
                        )
                        disabled_response["X-Session-ID"] = str(session.id)
                        return disabled_response

                    allowed, limit_message = check_daily_limit(request.user, "vision", profile=profile)
                    if not allowed:
                        limit_response = JsonResponse({"type": "error", "message": limit_message}, status=429)
                        limit_response["X-Session-ID"] = str(session.id)
                        return limit_response

                    # True vision: send every image straight to a vision-capable model
                    # in a single multi-image message.
                    try:
                        text_parts = []
                        for rec in saved_attachments:
                            if rec.file_type != "image":
                                extracted = _extract_attachment_text(rec, rec.original_name, os.path.splitext(rec.original_name)[1].lower())
                                text_parts.append(f"--- Attached file: {rec.original_name} ---\n{extracted}\n--- End attachment ---")
                        text_parts.append(user_query or (
                            "Describe this image." if len(image_files) == 1 else "Describe these images."
                        ))

                        content = [{"type": "text", "text": "\n\n".join(text_parts)}]
                        image_previews = []
                        filenames = []
                        for rec in saved_attachments:
                            if rec.file_type == "image":
                                try:
                                    rec.file.seek(0)
                                    image_bytes = rec.file.read()
                                except Exception:
                                    image_bytes = b""
                                mime = rec.mime_type or "image/jpeg"
                                data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
                                content.append({"type": "image_url", "image_url": {"url": data_uri}})
                                image_previews.append(rec.to_dict()["url"])
                                filenames.append(rec.original_name)

                        vision_messages = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": content}
                        ]
                        captured_usage = {}
                        resolved = {}
                        start_time = time.time()
                        vision_text = ai_vision(
                            model_id, vision_messages,
                            on_usage=captured_usage.update, on_model_resolved=resolved.update,
                        )
                        latency = round(time.time() - start_time, 2)
                        display_query = user_query or f"[{len(image_files)} image(s): {', '.join(filenames)}]"
                        stats = build_stats(
                            model_id=model_id, serving_model_id=model_id, resolved=resolved,
                            captured_usage=captured_usage,
                            prompt_text=display_query, completion_text=vision_text,
                            start_time=start_time,
                            streaming=False, is_vision=True, memory_used=False,
                        )

                        attachment_dicts = [r.to_dict() for r in saved_attachments]
                        user_msg, assistant_msg = append_turn(
                            session, display_query, vision_text,
                            user_extra_data={"attachments": attachment_dicts},
                            assistant_extra_data={
                                "type": "vision",
                                "filenames": filenames,
                                "image_previews": image_previews,
                                "filename": filenames[0],
                                "image_preview": image_previews[0] if image_previews else "",
                                "stats": stats,
                            },
                            latency=latency,
                        )
                        MessageAttachment.objects.filter(id__in=[r.id for r in saved_attachments]).update(message=user_msg)
                        record_usage(
                            request.user, session, model_config.provider, model_id, "vision",
                            prompt_text=display_query, completion_text=vision_text,
                            captured_usage=captured_usage, latency=latency,
                        )
                        logger.log_request(
                            provider=model_config.provider,
                            latency=latency,
                            prompt_length=len(user_query),
                            response_length=len(vision_text)
                        )
                        vision_response = JsonResponse({
                            "type": "vision",
                            "response": vision_text,
                            "image_previews": image_previews,
                            "filenames": filenames,
                            "attachments": attachment_dicts,
                            "message_id": assistant_msg.id,
                        })
                        vision_response["X-Session-ID"] = str(session.id)
                        return vision_response
                    except Exception as e:
                        logger.log_request(
                            provider=model_config.provider,
                            latency=0,
                            prompt_length=len(user_query),
                            response_length=0,
                            error=str(e),
                            category="vision_provider",
                        )
                        record_failure(request.user, session, model_config.provider, model_id, "vision")
                        vision_error = JsonResponse({
                            "type": "error",
                            "message": "Couldn't analyze that image. Please try again."
                        })
                        vision_error["X-Session-ID"] = str(session.id)
                        return vision_error
                else:
                    # No vision support (or no images attached): extract text from every
                    # attachment (OCR for images, direct extraction for documents) and
                    # fold it into the conversation as context for the normal chat flow.
                    extracted_blocks = []
                    for rec in saved_attachments:
                        extracted = _extract_attachment_text(rec, rec.original_name, os.path.splitext(rec.original_name)[1].lower())
                        extracted_blocks.append(f"--- Attached file: {rec.original_name} ---\n{extracted}\n--- End attachment ---")
                    context_block = "\n\n".join(extracted_blocks)
                    user_query_for_model = f"{context_block}\n\n{user_query}" if user_query else context_block
            else:
                user_query_for_model = user_query

            if model_config.supports_image_gen and not is_email_verified(request.user):
                verify_response = JsonResponse({
                    "type": "error",
                    "message": "Please verify your email to use Image Studio.",
                    "requires_verification": True,
                })
                verify_response["X-Session-ID"] = str(session.id)
                return verify_response

            if model_config.supports_image_gen:
                if not FeatureFlag.is_enabled('image_generation', default=True):
                    disabled_response = JsonResponse(
                        {"type": "error", "message": "Image generation is temporarily disabled by the administrator."}
                    )
                    disabled_response["X-Session-ID"] = str(session.id)
                    return disabled_response

                allowed, limit_message = check_daily_limit(request.user, "image", profile=profile)
                if not allowed:
                    limit_response = JsonResponse({"type": "error", "message": limit_message}, status=429)
                    limit_response["X-Session-ID"] = str(session.id)
                    return limit_response

                # Handle image generation
                try:
                    seed = request.POST.get('seed')
                    aspect_ratio = request.POST.get('aspect_ratio', '1:1')
                    if seed and seed.strip():
                        seed = int(seed.strip())
                    else:
                        seed = None
                    result = generate_image(user_query, seed, aspect_ratio)
                    
                    if not result.get("success", False):
                        error_response = JsonResponse({
                            "type": "error",
                            "message": result.get(
                                "message",
                                result.get("error", "Image generation failed.")
                            )
                        })
                        error_response["X-Session-ID"] = str(session.id)
                        return error_response

                    # Save the turn to the message tree
                    result.setdefault("generation_time", 0)
                    image_start_time = time.time() - result.get("generation_time", 0)
                    image_stats = build_stats(
                        model_id=model_id, serving_model_id=model_id,
                        prompt_text=user_query, completion_text="",
                        start_time=image_start_time, end_time=time.time(),
                        streaming=False, is_image_gen=True, memory_used=False,
                    )
                    image_stats["actual_model"] = result["model_used"]
                    attachment_dicts = [r.to_dict() for r in saved_attachments] if saved_attachments else None
                    _user_msg, assistant_msg = append_turn(
                        session, user_query, "",
                        user_extra_data={"attachments": attachment_dicts} if attachment_dicts else None,
                        assistant_extra_data={
                            "type": "image",
                            "image_url": result["image_url"],
                            "model_used": result["model_used"],
                            "prompt": result["prompt"],
                            "width": result["width"],
                            "height": result["height"],
                            "generation_time": result.get("generation_time", 0),
                            "stats": image_stats,
                        },
                        latency=result.get("generation_time", 0),
                    )
                    if saved_attachments:
                        MessageAttachment.objects.filter(id__in=[r.id for r in saved_attachments]).update(message=_user_msg)
                    record_usage(
                        request.user, session, "pollinations", model_id, "image",
                        prompt_text=user_query, latency=result.get("generation_time", 0),
                    )

                    image_response = JsonResponse({
                        "success": True,
                        "type": "image",
                        "url": result["image_url"],
                        "model_used": result["model_used"],
                        "prompt": result["prompt"],
                        "width": result["width"],
                        "height": result["height"],
                        "generation_time": result.get("generation_time", 0),
                        "message_id": assistant_msg.id,
                        "attachments": attachment_dicts or [],
                    })
                    image_response["X-Session-ID"] = str(session.id)
                    return image_response
                except Exception as e:
                    logger.log_request(
                        provider="pollinations",
                        latency=0,
                        prompt_length=len(user_query),
                        response_length=0,
                        error=str(e),
                        category="image_provider",
                    )
                    record_failure(request.user, session, "pollinations", model_id, "image")
                    error_response = JsonResponse({
                        "type": "error",
                        "message": "Image generation failed. Please try again."
                    })
                    error_response["X-Session-ID"] = str(session.id)
                    return error_response
            
            # Regular chat
            if not FeatureFlag.is_enabled('ai_chat', default=True):
                disabled_response = JsonResponse(
                    {"type": "error", "message": "AI Chat is temporarily disabled by the administrator."}
                )
                disabled_response["X-Session-ID"] = str(session.id)
                return disabled_response

            allowed, limit_message = check_daily_limit(request.user, "chat", profile=profile)
            if not allowed:
                limit_response = JsonResponse({"type": "error", "message": limit_message}, status=429)
                limit_response["X-Session-ID"] = str(session.id)
                return limit_response

            # Desktop Agent execution layer
            if not attachments and default_agent_controller.can_handle(user_query):
                def agent_stream_generator():
                    full_response = ""
                    start_time = time.time()

                    def synthesize_code_or_text(prompt_text):
                        gen_messages = [
                            {"role": "system", "content": "You are a code and text generator. Output ONLY the raw code or text requested. Do not include markdown fences, backticks, conversational preamble, or explanations."},
                            {"role": "user", "content": prompt_text}
                        ]
                        gen_tokens, _, _ = _stream_with_failover(model_id, gen_messages, lambda u: None)
                        parts = []
                        for t, is_notice in gen_tokens:
                            if not is_notice:
                                parts.append(t)
                        raw_gen = "".join(parts).strip()
                        if raw_gen.startswith("```"):
                            lines = raw_gen.split("\n")
                            if lines[0].startswith("```"):
                                lines = lines[1:]
                            if lines and lines[-1].strip() == "```":
                                lines = lines[:-1]
                            raw_gen = "\n".join(lines).strip()
                        return raw_gen

                    planner_model = "ox-alpha" if "ox-alpha" in MODEL_REGISTRY else model_id

                    def ox_alpha_planner(prompt_text):
                        gen_messages = [
                            {"role": "system", "content": "You are SIMBA_INTEL Desktop Agent Planner. Output strictly valid JSON without preamble."},
                            {"role": "user", "content": prompt_text}
                        ]
                        gen_tokens, _, _ = _stream_with_failover(planner_model, gen_messages, lambda u: None)
                        parts = [t for t, is_notice in gen_tokens if not is_notice]
                        return "".join(parts).strip()

                    try:
                        agent_gen = default_agent_controller.execute_and_stream(
                            user_query,
                            user_id=request.user.id,
                            planner_llm_fn=ox_alpha_planner,
                            text_generator_fn=synthesize_code_or_text,
                        )
                        for chunk in agent_gen:
                            if not chunk.startswith("SIMBA_STATUS:"):
                                full_response += chunk
                            yield chunk
                    except Exception as e:
                        logger.log_request(
                            provider=model_config.provider,
                            latency=time.time() - start_time,
                            prompt_length=len(user_query),
                            response_length=len(full_response),
                            error=str(e)
                        )
                        record_failure(request.user, session, model_config.provider, model_id, "agent", latency=time.time() - start_time)
                        yield "\n\nEncountered an issue executing the desktop action. Please try again."
                    else:
                        latency = round(time.time() - start_time, 2)
                        actual_config = get_model_config(model_id)
                        if full_response.strip():
                            is_first_turn = not session.thread.exists()
                            stats = build_stats(
                                model_id=model_id, serving_model_id=model_id,
                                prompt_text=user_query, completion_text=full_response,
                                start_time=start_time,
                                streaming=True, memory_used=False,
                            )
                            user_msg, assistant_msg = append_turn(
                                session, user_query, full_response,
                                assistant_extra_data={"type": "agent_action", "stats": stats},
                                latency=latency,
                            )
                            record_usage(
                                request.user, session, "local", "agent", "agent",
                                prompt_text="", completion_text="",
                                latency=latency,
                            )
                            if is_first_turn:
                                if not session.title or session.title in ["New Chat", "Untitled", "New Conversation"]:
                                    session.title = user_query.strip().capitalize()[:40]
                                    session.save(update_fields=["title"])
                        logger.log_request(
                            provider="local",
                            latency=latency,
                            prompt_length=len(user_query),
                            response_length=len(full_response)
                        )

                agent_response = StreamingHttpResponse(agent_stream_generator(), content_type="text/plain")
                agent_response["X-Session-ID"] = str(session.id)
                return agent_response

            chat_system_prompt = SYSTEM_PROMPT
            memory_used = False
            if profile.memory_enabled:
                memory_context = get_user_memory_context(request.user)
                if memory_context:
                    chat_system_prompt = f"{SYSTEM_PROMPT}\n\n{memory_context}"
                    memory_used = True
            messages = build_context_messages(session, user_query_for_model, chat_system_prompt)
            is_search_augmented = False
            if FeatureFlag.is_enabled('web_search', default=True) and _is_search_query(user_query_for_model):
                search_results = _get_web_search_results(user_query_for_model)
                if search_results:
                    context_str = "\n\n".join([f"- {result['title']}: {result['content']}" for result in search_results])
                    augmented_query = (
                        f"{user_query_for_model}\n\nRelevant search results:\n{context_str}"
                        "\n\nIf you include an image for a specific product, gift, place, "
                        "animal, or similar item, give it a short, precise caption (used as "
                        "the image's alt text) that names exactly that one item, nothing else."
                    )
                    messages[-1]['content'] = augmented_query
                    is_search_augmented = True

            def stream_generator():
                full_response = ""
                start_time = time.time()
                first_token_time = None
                captured_usage = {}
                token_gen, serving, resolved = _stream_with_failover(model_id, messages, captured_usage.update)
                if is_search_augmented:
                    token_gen = _rewrite_images_in_stream(token_gen)
                try:
                    for token, is_notice in token_gen:
                        if not is_notice:
                            if first_token_time is None:
                                first_token_time = time.time()
                            full_response += token
                        yield token
                except Exception as e:
                    logger.log_request(
                        provider=model_config.provider,
                        latency=time.time() - start_time,
                        prompt_length=len(user_query),
                        response_length=len(full_response),
                        error=str(e)
                    )
                    record_failure(request.user, session, model_config.provider, model_id, "chat", latency=time.time() - start_time)
                    # The real exception (str(e)) is already captured above via
                    # logger.log_request for server-side diagnosis - it must
                    # never reach the client as-is, since provider errors can
                    # contain internal details (hostnames, request payloads,
                    # etc.) that aren't safe to show a user mid-stream.
                    yield "\n\nSomething went wrong while generating a response. Please try again."
                else:
                    latency = round(time.time() - start_time, 2)
                    actual_config = get_model_config(serving["model_id"])
                    if full_response.strip():
                        is_first_turn = not session.thread.exists()
                        stats = build_stats(
                            model_id=model_id, serving_model_id=serving["model_id"], resolved=resolved,
                            captured_usage=captured_usage,
                            prompt_text=user_query_for_model, completion_text=full_response,
                            start_time=start_time,
                            first_token_time=first_token_time, streaming=True, memory_used=memory_used,
                        )
                        attachment_dicts = [r.to_dict() for r in saved_attachments] if saved_attachments else None
                        clean_user_content = user_query or (f"[{len(saved_attachments)} attachment(s)]" if saved_attachments else "")
                        user_msg, assistant_msg = append_turn(
                            session, clean_user_content, full_response,
                            user_extra_data={"attachments": attachment_dicts} if attachment_dicts else None,
                            assistant_extra_data={"stats": stats},
                            latency=latency,
                        )
                        if saved_attachments:
                            MessageAttachment.objects.filter(id__in=[r.id for r in saved_attachments]).update(message=user_msg)
                        record_usage(
                            request.user, session, actual_config.provider, serving["model_id"], "chat",
                            prompt_text=user_query_for_model, completion_text=full_response,
                            captured_usage=captured_usage, latency=latency,
                        )
                        # Both best-effort and non-blocking to the response
                        # already sent above - a failure here never affects
                        # the reply the user just received (see their own
                        # docstrings/try-excepts in conversation_memory.py
                        # and conversation_intelligence.py).
                        if is_first_turn:
                            maybe_generate_smart_title(session, user_query_for_model, full_response)
                        maybe_summarize_session(session)
                        if profile.memory_enabled:
                            extract_and_store_facts(request.user, session)
                    logger.log_request(
                        provider=actual_config.provider,
                        latency=latency,
                        prompt_length=len(user_query),
                        response_length=len(full_response)
                    )
            response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
            response["X-Session-ID"] = str(session.id)
            return response
        except Exception as e:
            logger.log_request(
                provider=model_id,
                latency=0,
                prompt_length=len(user_query),
                response_length=0,
                error=str(e)
            )
            return JsonResponse({"response": "Something went wrong. Please try again."}, status=500)
    return JsonResponse({"error": "Invalid request"}, status=400)


@login_required
def session_active_leaf(request, session_id):
    """Lightweight lookup so the frontend can learn the id of a message that
    was just streamed (streaming responses can't carry a trailing header/body
    field once the body has started, since the new Message's id isn't known
    until the stream finishes) - enables true sibling-branch regenerate on a
    message from the same page session, without requiring a reload first."""
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    leaf = session.active_leaf
    user_message_id = leaf.parent_id if leaf and leaf.role == "assistant" else None
    return JsonResponse({"message_id": session.active_leaf_id, "user_message_id": user_message_id})


@login_required
def session_suggest_followups(request, session_id):
    """On-demand only (see conversation_intelligence.suggest_followups'
    docstring) - the frontend calls this after a reply finishes rendering,
    rather than it running automatically on every single turn.

    `message_id` (Sprint 2 regression fix): the frontend passes the exact
    reply the "Suggest Follow-ups" button is attached to, so suggestions are
    always generated from THAT message's content. Falling back to session.
    active_leaf unconditionally (the old behavior) was correct only for a
    strictly linear conversation - the moment edit/regenerate/branch-switch
    can make the active leaf diverge from an older, still-visible reply, a
    click on that older reply's button would silently return suggestions
    for whatever the session's current leaf happens to be instead (wrong
    content, sometimes not even an assistant message, hence occasionally
    empty). message_id is still validated against this session and role
    before use, so a stale/foreign id degrades to the old fallback rather
    than ever leaking another session's content."""
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    message_id = request.GET.get('message_id', '').strip()
    leaf = None
    if message_id:
        leaf = Message.objects.filter(id=message_id, session=session, role='assistant').first()
    if leaf is None:
        leaf = session.active_leaf
    if not leaf or leaf.role != "assistant" or not (leaf.content or "").strip():
        return JsonResponse({"suggestions": []})
    return JsonResponse({"suggestions": suggest_followups(leaf.content)})


@login_required
def session_related_conversations(request, session_id):
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    related = find_related_conversations(session)
    return JsonResponse({"results": [{"id": s.id, "title": s.title} for s in related]})


@login_required
def message_siblings(request, message_id):
    """Lets the frontend refresh a branch-switcher pill right after a
    regenerate/edit completes, without a full page reload - regenerateText()
    and submitEditedMessage() both patch the DOM in place, so they need a
    way to learn "how many siblings does this turn have now" on demand."""
    msg = get_object_or_404(Message, id=message_id, session__user=request.user)
    # session_id, not session: msg.session is already known by id here, so
    # filtering on the id avoids fetching the ChatSession object just to
    # turn around and filter by it.
    sibling_ids = list(
        Message.objects.filter(session_id=msg.session_id, parent_id=msg.parent_id, role=msg.role)
        .order_by("created_at").values_list("id", flat=True)
    )
    return JsonResponse({"sibling_ids": sibling_ids, "current_id": msg.id, "role": msg.role})


@login_required
def regenerate_message(request, message_id):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    if not FeatureFlag.is_enabled('ai_chat', default=True):
        return JsonResponse({"type": "error", "message": "AI Chat is temporarily disabled by the administrator."})

    if not check_rate_limit(request.user):
        return JsonResponse(
            {"type": "error", "message": "You're sending requests too quickly. Please wait a moment and try again."},
            status=429
        )
    allowed, limit_message = check_daily_limit(request.user, "chat")
    if not allowed:
        return JsonResponse({"type": "error", "message": limit_message}, status=429)

    old_msg = get_object_or_404(
        Message.objects.select_related('session', 'parent'),
        id=message_id, role='assistant', session__user=request.user,
    )
    routing_profile = UserProfile.get_or_create_for(request.user)
    model_id = request.POST.get('model_id') or request.session.get('selected_model', routing_profile.default_model)
    user_query = old_msg.parent.content if old_msg.parent else ""
    if model_id.lower() == "auto":
        model_id = resolve_model_id(model_id, user_query, False, routing_profile.default_model)

    try:
        model_config = get_model_config(model_id)
    except KeyError:
        return JsonResponse({"type": "error", "message": "Invalid model selection."}, status=400)

    # Context up to (but excluding) the user turn this reply answers - it
    # gets appended separately by build_messages, same as the normal send flow.
    history_chain = walk_chain_from(old_msg.parent)[:-1]
    history = messages_to_history_dicts(history_chain)
    messages = build_messages(user_query, history)

    def stream_generator():
        full_response = ""
        start_time = time.time()
        first_token_time = None
        captured_usage = {}
        token_gen, serving, resolved = _stream_with_failover(model_id, messages, captured_usage.update)
        try:
            for token, is_notice in token_gen:
                if not is_notice:
                    if first_token_time is None:
                        first_token_time = time.time()
                    full_response += token
                yield token
        except Exception as e:
            logger.log_request(
                provider=model_config.provider,
                latency=time.time() - start_time,
                prompt_length=len(user_query),
                response_length=len(full_response),
                error=str(e)
            )
            record_failure(request.user, session, model_config.provider, model_id, "chat", latency=time.time() - start_time)
            # The real exception (str(e)) is already captured above via
            # logger.log_request for server-side diagnosis - it must never
            # reach the client as-is, since provider errors can contain
            # internal details (hostnames, request payloads, etc.) that
            # aren't safe to show a user mid-stream.
            yield "\n\nSomething went wrong while generating a response. Please try again."
        else:
            latency = round(time.time() - start_time, 2)
            actual_config = get_model_config(serving["model_id"])
            if full_response.strip():
                stats = build_stats(
                    model_id=model_id, serving_model_id=serving["model_id"], resolved=resolved,
                    captured_usage=captured_usage,
                    prompt_text=user_query, completion_text=full_response,
                    start_time=start_time,
                    first_token_time=first_token_time, streaming=True, memory_used=False,
                )
                regenerate_assistant_reply(old_msg, full_response, extra_data={"stats": stats}, latency=latency)
                record_usage(
                    request.user, session, actual_config.provider, serving["model_id"], "chat",
                    prompt_text=user_query, completion_text=full_response,
                    captured_usage=captured_usage, latency=latency,
                )
            logger.log_request(
                provider=actual_config.provider,
                latency=latency,
                prompt_length=len(user_query),
                response_length=len(full_response)
            )

    response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
    response["X-Session-ID"] = str(session.id)
    return response


@login_required
def edit_message(request, message_id):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    if not FeatureFlag.is_enabled('ai_chat', default=True):
        return JsonResponse({"type": "error", "message": "AI Chat is temporarily disabled by the administrator."})

    if not check_rate_limit(request.user):
        return JsonResponse(
            {"type": "error", "message": "You're sending requests too quickly. Please wait a moment and try again."},
            status=429
        )
    allowed, limit_message = check_daily_limit(request.user, "chat")
    if not allowed:
        return JsonResponse({"type": "error", "message": limit_message}, status=429)

    old_msg = get_object_or_404(
        Message.objects.select_related('session', 'parent'),
        id=message_id, role='user', session__user=request.user,
    )
    session = old_msg.session
    new_content = request.POST.get('content', '').strip()
    if not new_content:
        return JsonResponse({"response": "Query cannot be empty"}, status=400)

    routing_profile = UserProfile.get_or_create_for(request.user)
    model_id = request.POST.get('model_id') or request.session.get('selected_model', routing_profile.default_model)
    if model_id.lower() == "auto":
        model_id = resolve_model_id(model_id, new_content, False, routing_profile.default_model)

    try:
        model_config = get_model_config(model_id)
    except KeyError:
        return JsonResponse({"type": "error", "message": "Invalid model selection."}, status=400)

    # Context = everything before the message being edited - the edited turn
    # itself is passed separately as the new user_query.
    history_chain = walk_chain_from(old_msg.parent)
    history = messages_to_history_dicts(history_chain)
    messages = build_messages(new_content, history)

    def stream_generator():
        full_response = ""
        start_time = time.time()
        first_token_time = None
        captured_usage = {}
        token_gen, serving, resolved = _stream_with_failover(model_id, messages, captured_usage.update)
        try:
            for token, is_notice in token_gen:
                if not is_notice:
                    if first_token_time is None:
                        first_token_time = time.time()
                    full_response += token
                yield token
        except Exception as e:
            logger.log_request(
                provider=model_config.provider,
                latency=time.time() - start_time,
                prompt_length=len(new_content),
                response_length=len(full_response),
                error=str(e)
            )
            record_failure(request.user, session, model_config.provider, model_id, "chat", latency=time.time() - start_time)
            # The real exception (str(e)) is already captured above via
            # logger.log_request for server-side diagnosis - it must never
            # reach the client as-is, since provider errors can contain
            # internal details (hostnames, request payloads, etc.) that
            # aren't safe to show a user mid-stream.
            yield "\n\nSomething went wrong while generating a response. Please try again."
        else:
            latency = round(time.time() - start_time, 2)
            actual_config = get_model_config(serving["model_id"])
            if full_response.strip():
                stats = build_stats(
                    model_id=model_id, serving_model_id=serving["model_id"], resolved=resolved,
                    captured_usage=captured_usage,
                    prompt_text=new_content, completion_text=full_response,
                    start_time=start_time,
                    first_token_time=first_token_time, streaming=True, memory_used=False,
                )
                append_turn(
                    session, new_content, full_response, assistant_extra_data={"stats": stats},
                    latency=latency, parent=old_msg.parent,
                )
                record_usage(
                    request.user, session, actual_config.provider, serving["model_id"], "chat",
                    prompt_text=new_content, completion_text=full_response,
                    captured_usage=captured_usage, latency=latency,
                )
            logger.log_request(
                provider=actual_config.provider,
                latency=latency,
                prompt_length=len(new_content),
                response_length=len(full_response)
            )

    response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
    response["X-Session-ID"] = str(session.id)
    return response


@login_required
def switch_branch(request, message_id):
    """New UI feature: lets the frontend switch which sibling branch (an
    edited user turn, or a regenerated assistant reply) is active, without
    creating a new branch - this is the missing counterpart to regenerate/
    edit, which have created real sibling branches since Phase 3 but had no
    way to navigate back to an older one until now."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    msg = get_object_or_404(Message.objects.select_related('session'), id=message_id, session__user=request.user)
    session = msg.session

    if msg.role == "assistant":
        leaf = msg
    elif msg.role == "user":
        leaf = msg.children.filter(role="assistant").order_by("-created_at").first() or msg
    else:
        return JsonResponse({"type": "error", "message": "Cannot switch to this message type."}, status=400)

    set_active_leaf(session, leaf)
    return JsonResponse({
        "status": "success",
        "message_id": leaf.id,
        "user_message_id": leaf.parent_id if leaf.role == "assistant" else leaf.id,
    })


@login_required
def toggle_favorite_image(request, message_id):
    """Generated images live entirely inside Message.extra_data (there's no
    separate Image model) - favoriting just flips a flag in that same JSON
    blob rather than introducing a new table for what's a single boolean."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    msg = get_object_or_404(Message, id=message_id, session__user=request.user, role="assistant")
    if not msg.extra_data or msg.extra_data.get("type") != "image":
        return JsonResponse({"type": "error", "message": "Not an image message."}, status=400)

    msg.extra_data["favorited"] = not msg.extra_data.get("favorited", False)
    msg.save(update_fields=["extra_data"])
    return JsonResponse({"status": "success", "favorited": msg.extra_data["favorited"]})


@login_required
def bookmark_message(request, message_id):
    """Bookmarking a message (any role/type) - distinct from
    toggle_favorite_image, which only applies to a generated image card.
    Reuses the same extra_data JSON blob pattern rather than a new table,
    same reasoning as that view."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    msg = get_object_or_404(Message, id=message_id, session__user=request.user)
    extra_data = msg.extra_data or {}
    extra_data["bookmarked"] = not extra_data.get("bookmarked", False)
    if extra_data["bookmarked"]:
        extra_data["bookmarked_at"] = timezone.now().isoformat()
    msg.extra_data = extra_data
    msg.save(update_fields=["extra_data"])
    return JsonResponse({"status": "success", "bookmarked": extra_data["bookmarked"]})


@login_required
def message_info(request, message_id):
    """Read side of the Message Information Panel - returns exactly the
    real, backend-captured metadata stored in extra_data['stats'] at
    generation time (see chat/services/message_stats.py's build_stats and
    its call sites in ask_ai/regenerate_message/edit_message/
    continue_message). Never estimates or fabricates: a message with no
    stats recorded (e.g. one created before this feature existed) returns
    has_stats=false, and the frontend must show "not available" rather than
    inventing a value."""
    msg = get_object_or_404(Message, id=message_id, session__user=request.user, role="assistant")
    stats = (msg.extra_data or {}).get("stats")
    if not stats:
        return JsonResponse({"status": "success", "has_stats": False})
    return JsonResponse({"status": "success", "has_stats": True, "stats": stats})


@login_required
def bookmarks_list(request):
    """Read side of the Bookmarks panel - every bookmarked message across all
    of the user's sessions (any role/type: chat, vision, or image), newest
    bookmark first. `q` filters by conversation title, the custom bookmark
    label, or the message content itself, matching how sessions/search/
    already searches title+content. A soft cap keeps this cheap even for a
    user with hundreds of bookmarks; there's no pagination yet since a
    single-page list this size is standard for a bookmarks/favorites panel
    in comparable products."""
    q = request.GET.get('q', '').strip()

    candidates = Message.objects.filter(
        session__user=request.user, extra_data__bookmarked=True,
    ).select_related('session').order_by('-id')[:500]

    results = []
    for msg in candidates:
        extra = msg.extra_data or {}
        label = extra.get('bookmark_label', '')
        session_title = msg.session.title
        if msg.role == 'assistant' and extra.get('type') == 'image':
            snippet = extra.get('prompt', '') or 'Generated image'
            msg_type = 'image'
        elif msg.role == 'assistant' and extra.get('type') == 'vision':
            snippet = msg.content
            msg_type = 'vision'
        else:
            snippet = msg.content
            msg_type = 'chat'
        snippet = (snippet or '').strip()

        if q:
            haystack = f"{session_title} {label} {snippet}".lower()
            if q.lower() not in haystack:
                continue

        results.append({
            'message_id': msg.id,
            'session_id': msg.session_id,
            'session_title': session_title,
            'label': label,
            'type': msg_type,
            'snippet': snippet[:220],
            'image_url': extra.get('image_url', ''),
            'bookmarked_at': extra.get('bookmarked_at'),
        })

    results.sort(key=lambda r: r['bookmarked_at'] or '', reverse=True)
    return JsonResponse({'results': results[:200]})


@login_required
def set_bookmark_label(request, message_id):
    """Renames a bookmark - a personal label stored on the bookmark itself,
    independent of the conversation's own title, the same distinction
    browser bookmarks draw between a saved title and the page's real one."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    msg = get_object_or_404(Message, id=message_id, session__user=request.user)
    extra_data = msg.extra_data or {}
    if not extra_data.get("bookmarked"):
        return JsonResponse({"error": "This message isn't bookmarked."}, status=400)
    label = request.POST.get('label', '').strip()[:120]
    extra_data["bookmark_label"] = label
    msg.extra_data = extra_data
    msg.save(update_fields=["extra_data"])
    return JsonResponse({"status": "success", "label": label})


# ================= Prompt Library (Part 5) =================

def _serialize_saved_prompt(p):
    return {
        "id": p.id,
        "title": p.title,
        "content": p.content,
        "category": p.category,
        "is_favorite": p.is_favorite,
        "use_count": p.use_count,
    }


@login_required
def saved_prompts_list(request):
    """Powers the whole Prompt Library panel - `q` searches title+content,
    `category` filters to an exact category, `favorites=1` restricts to
    favorited prompts. All three can combine (e.g. favorites within one
    category matching a search term)."""
    from chat.models import SavedPrompt

    qs = SavedPrompt.objects.filter(user=request.user)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(models.Q(title__icontains=q) | models.Q(content__icontains=q))
    category = request.GET.get('category', '').strip()
    if category:
        qs = qs.filter(category=category)
    if request.GET.get('favorites') == '1':
        qs = qs.filter(is_favorite=True)

    categories = list(
        SavedPrompt.objects.filter(user=request.user).exclude(category='')
        .values_list('category', flat=True).distinct().order_by('category')
    )
    return JsonResponse({
        "results": [_serialize_saved_prompt(p) for p in qs[:200]],
        "categories": categories,
    })


@login_required
def create_saved_prompt(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import SavedPrompt

    title = request.POST.get('title', '').strip()[:100]
    content = request.POST.get('content', '').strip()
    category = request.POST.get('category', '').strip()[:50]
    if not content:
        return JsonResponse({"error": "Prompt content can't be empty."}, status=400)
    if not title:
        title = content[:40]
    prompt = SavedPrompt.objects.create(user=request.user, title=title, content=content, category=category)
    return JsonResponse({"status": "success", "prompt": _serialize_saved_prompt(prompt)})


@login_required
def update_saved_prompt(request, prompt_id):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import SavedPrompt

    prompt = get_object_or_404(SavedPrompt, id=prompt_id, user=request.user)
    if 'title' in request.POST:
        prompt.title = request.POST.get('title', '').strip()[:100] or prompt.title
    if 'content' in request.POST:
        new_content = request.POST.get('content', '').strip()
        if new_content:
            prompt.content = new_content
    if 'category' in request.POST:
        prompt.category = request.POST.get('category', '').strip()[:50]
    if 'is_favorite' in request.POST:
        prompt.is_favorite = request.POST.get('is_favorite') == '1'
    prompt.save()
    return JsonResponse({"status": "success", "prompt": _serialize_saved_prompt(prompt)})


@login_required
def delete_saved_prompt(request, prompt_id):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import SavedPrompt

    prompt = get_object_or_404(SavedPrompt, id=prompt_id, user=request.user)
    prompt.delete()
    return JsonResponse({"status": "success"})


@login_required
def use_saved_prompt(request, prompt_id):
    """Increments use_count (surfaces "most used" ordering potential later)
    and hands back the content for the composer to insert - a separate
    write endpoint rather than folding this into the read-side list view,
    so simply opening the library panel is never itself counted as a use."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import SavedPrompt

    prompt = get_object_or_404(SavedPrompt, id=prompt_id, user=request.user)
    prompt.use_count = models.F('use_count') + 1
    prompt.save(update_fields=['use_count'])
    prompt.refresh_from_db()
    return JsonResponse({"status": "success", "content": prompt.content})


@login_required
def recent_prompts(request):
    """Prompt History/Recent Prompts - reads directly from the user's own
    past user-turn Messages rather than a separate log, deduped by exact
    text (typing the same short prompt many times shouldn't flood this list
    with identical entries) and capped to a reasonable recency window."""
    limit = 20
    seen = set()
    results = []
    qs = (
        Message.objects.filter(session__user=request.user, role='user')
        .exclude(content='')
        .order_by('-created_at')
        .values_list('content', 'created_at')[:200]
    )
    for content, created_at in qs:
        key = content.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        results.append({"content": content, "created_at": created_at.isoformat()})
        if len(results) >= limit:
            break
    return JsonResponse({"results": results})


@login_required
def delete_message(request, message_id):
    """Deletes one message and everything under it in the tree (Message.
    parent's on_delete=CASCADE handles descendants automatically). If the
    session's active_leaf was the deleted node or one of its descendants,
    it no longer exists afterward - falls back to whatever message was most
    recently created in this session, or None if the tree is now empty."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    msg = get_object_or_404(Message.objects.select_related('session'), id=message_id, session__user=request.user)
    session = msg.session
    msg.delete()

    if session.active_leaf_id and not Message.objects.filter(id=session.active_leaf_id).exists():
        fallback = Message.objects.filter(session=session).order_by('-created_at').first()
        session.active_leaf = fallback
        session.save(update_fields=["active_leaf"])

    return JsonResponse({"status": "success"})


@login_required
def continue_message(request, message_id):
    """Extends an assistant reply that got cut short, in place - unlike
    regenerate (a fresh sibling reply) this appends new tokens onto the SAME
    message, since the point is "keep going from where you stopped", not
    "try again". The model sees its own partial reply as the last assistant
    turn plus an explicit instruction not to repeat itself, mirroring
    regenerate_message's streaming structure exactly."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    if not FeatureFlag.is_enabled('ai_chat', default=True):
        return JsonResponse({"type": "error", "message": "AI Chat is temporarily disabled by the administrator."})

    if not check_rate_limit(request.user):
        return JsonResponse(
            {"type": "error", "message": "You're sending requests too quickly. Please wait a moment and try again."},
            status=429
        )
    allowed, limit_message = check_daily_limit(request.user, "chat")
    if not allowed:
        return JsonResponse({"type": "error", "message": limit_message}, status=429)

    old_msg = get_object_or_404(
        Message.objects.select_related('session', 'parent'),
        id=message_id, role='assistant', session__user=request.user,
    )
    session = old_msg.session
    routing_profile = UserProfile.get_or_create_for(request.user)
    model_id = request.POST.get('model_id') or request.session.get('selected_model', routing_profile.default_model)
    user_query = old_msg.parent.content if old_msg.parent else ""
    if model_id.lower() == "auto":
        model_id = resolve_model_id(model_id, user_query, False, routing_profile.default_model)

    try:
        model_config = get_model_config(model_id)
    except KeyError:
        return JsonResponse({"type": "error", "message": "Invalid model selection."}, status=400)

    history_chain = walk_chain_from(old_msg.parent)[:-1]
    history = messages_to_history_dicts(history_chain)
    messages = build_messages(user_query, history)
    messages.append({"role": "assistant", "content": old_msg.content})
    messages.append({"role": "user", "content": "Continue exactly where you left off. Do not repeat what you already said."})

    def stream_generator():
        full_response = ""
        start_time = time.time()
        first_token_time = None
        captured_usage = {}
        token_gen, serving, resolved = _stream_with_failover(model_id, messages, captured_usage.update)
        try:
            for token, is_notice in token_gen:
                if not is_notice:
                    if first_token_time is None:
                        first_token_time = time.time()
                    full_response += token
                yield token
        except Exception as e:
            logger.log_request(
                provider=model_config.provider,
                latency=time.time() - start_time,
                prompt_length=len(user_query),
                response_length=len(full_response),
                error=str(e)
            )
            record_failure(request.user, session, model_config.provider, model_id, "chat", latency=time.time() - start_time)
            # The real exception (str(e)) is already captured above via
            # logger.log_request for server-side diagnosis - it must never
            # reach the client as-is, since provider errors can contain
            # internal details (hostnames, request payloads, etc.) that
            # aren't safe to show a user mid-stream.
            yield "\n\nSomething went wrong while generating a response. Please try again."
        else:
            latency = round(time.time() - start_time, 2)
            actual_config = get_model_config(serving["model_id"])
            if full_response.strip():
                stats = build_stats(
                    model_id=model_id, serving_model_id=serving["model_id"], resolved=resolved,
                    captured_usage=captured_usage,
                    prompt_text=user_query, completion_text=full_response,
                    start_time=start_time,
                    first_token_time=first_token_time, streaming=True, memory_used=False,
                )
                old_msg.content = old_msg.content + full_response
                old_msg.latency = (old_msg.latency or 0) + latency
                old_msg.extra_data = {**(old_msg.extra_data or {}), "stats": stats}
                old_msg.save(update_fields=["content", "latency", "extra_data"])
                record_usage(
                    request.user, session, actual_config.provider, serving["model_id"], "chat",
                    prompt_text=user_query, completion_text=full_response,
                    captured_usage=captured_usage, latency=latency,
                )
            logger.log_request(
                provider=actual_config.provider,
                latency=latency,
                prompt_length=len(user_query),
                response_length=len(full_response)
            )

    response = StreamingHttpResponse(stream_generator(), content_type="text/plain")
    response["X-Session-ID"] = str(session.id)
    return response


@login_required
def delete_session(request, session_id):
    if request.method == "POST":
        get_object_or_404(ChatSession, id=session_id, user=request.user).delete()
        return JsonResponse({"status": "success"})


@login_required
def rename_session(request, session_id):
    if request.method == "POST":
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.title = request.POST.get('title')
        session.save()
        return JsonResponse({"status": "success"})


@login_required
def pin_session(request, session_id):
    if request.method == "POST":
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        session.is_pinned = not session.is_pinned
        session.save(update_fields=["is_pinned"])
        return JsonResponse({"status": "success", "is_pinned": session.is_pinned})


@login_required
def toggle_archive_session(request, session_id):
    """Archiving is a soft hide (excluded from the default sidebar list,
    reachable via the Archived view) - never a delete. See ChatSession.
    is_archived's docstring."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    session.is_archived = not session.is_archived
    session.save(update_fields=["is_archived"])
    return JsonResponse({"status": "success", "is_archived": session.is_archived})


@login_required
def toggle_favorite_session(request, session_id):
    """Favorites a whole conversation - distinct from toggle_favorite_image,
    which favorites one generated image inside a turn."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    session.is_favorite = not session.is_favorite
    session.save(update_fields=["is_favorite"])
    return JsonResponse({"status": "success", "is_favorite": session.is_favorite})


@login_required
def duplicate_session(request, session_id):
    """Deep-copies a session's entire message tree (not just the title) -
    branch structure, edits, and regenerated siblings all come along, so the
    duplicate is a genuine independent fork, not just an empty chat with the
    same name."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    original = get_object_or_404(ChatSession, id=session_id, user=request.user)
    new_session = ChatSession.objects.create(
        user=request.user, title=f"{original.title} (copy)", folder=original.folder,
    )
    # `thread` is ordered by created_at (Message.Meta), so every parent is
    # already in id_map by the time its children are processed - one pass,
    # no second lookup query needed.
    id_map = {}
    new_active_leaf = None
    for old_msg in original.thread.order_by('created_at'):
        new_msg = Message.objects.create(
            session=new_session, role=old_msg.role, content=old_msg.content,
            parent=id_map.get(old_msg.parent_id), extra_data=old_msg.extra_data,
            latency=old_msg.latency,
        )
        id_map[old_msg.id] = new_msg
        if old_msg.id == original.active_leaf_id:
            new_active_leaf = new_msg
    if new_active_leaf:
        new_session.active_leaf = new_active_leaf
        new_session.save(update_fields=["active_leaf"])

    # Rendered server-side and handed back as HTML (Part 1 - no reload):
    # the sidebar row needs the exact same structure/dropdown every other
    # row has, and re-deriving that in JS would just be a second copy of
    # partials/_chat_row.html drifting out of sync with the first.
    new_session.date_group = 'today'
    row_html = render_to_string(
        'partials/_chat_row.html', {'s': new_session, 'current_session': None}, request=request,
    )
    return JsonResponse({"status": "success", "session_id": new_session.id, "row_html": row_html})


@login_required
def bulk_session_action(request):
    """Powers the sidebar's multi-select toolbar - delete/archive/unarchive
    across however many sessions are checked, in one request instead of one
    round-trip per chat."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    action = request.POST.get('action')
    session_ids = request.POST.getlist('session_ids')
    sessions = ChatSession.objects.filter(id__in=session_ids, user=request.user)
    if action == 'delete':
        # QuerySet.delete() already returns how many rows it removed per
        # model - reading ChatSession's own count from that instead of a
        # separate .count() call beforehand saves a query without changing
        # what "count" means here (deleted sessions, not cascaded messages).
        _total_deleted, deleted_by_model = sessions.delete()
        count = deleted_by_model.get('chat.ChatSession', 0)
    elif action == 'archive':
        count = sessions.update(is_archived=True)
    elif action == 'unarchive':
        count = sessions.update(is_archived=False)
    else:
        return JsonResponse({"error": "Unknown action"}, status=400)
    return JsonResponse({"status": "success", "count": count})


@login_required
def set_session_folder(request, session_id):
    """Move a single chat into a folder (or out of one, when folder=''). If
    the target folder has no metadata row yet, one is created lazily so a
    freshly-typed folder name immediately gets a colour-swatch entry in the
    manager - keeps the string-membership and the metadata rows in sync."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import Folder

    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    folder_name = request.POST.get('folder', '').strip()[:100]
    session.folder = folder_name
    session.save(update_fields=["folder"])
    if folder_name:
        Folder.objects.get_or_create(user=request.user, name=folder_name)
    return JsonResponse({"status": "success", "folder": session.folder})


@login_required
def folders_summary(request):
    """Read-only refresh point for the sidebar's folder chips (Part 1 - no
    reload) - a folder create/rename/delete/recolor or a chat's folder
    changing calls this to re-render just the chip strip via JS instead of
    a full page reload."""
    return JsonResponse({'folders': _compute_folders_for_user(request.user)})


@login_required
def create_folder(request):
    """Create an empty folder (metadata row) so it appears in the manager
    before any chat is filed into it - the composer/move flow can then move
    chats into it by name."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import Folder

    name = request.POST.get('name', '').strip()[:100]
    if not name:
        return JsonResponse({"error": "Folder name can't be empty."}, status=400)
    color = request.POST.get('color', '').strip()
    valid_colors = {c for c, _ in ChatSession.COLOR_CHOICES}
    if color not in valid_colors:
        color = ''
    folder, created = Folder.objects.get_or_create(
        user=request.user, name=name, defaults={'color': color},
    )
    if not created:
        return JsonResponse({"error": "A folder with that name already exists."}, status=400)
    return JsonResponse({"status": "success", "name": folder.name, "color": folder.color})


@login_required
def rename_folder(request):
    """Rename a folder: updates the metadata row AND every chat filed under
    the old name in one shot. If a folder with the new name already exists,
    this MERGES into it (chats from both end up under the new name and the
    old metadata row is removed) rather than erroring - the least surprising
    outcome when a user renames "work" onto an existing "Work"."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import Folder

    old_name = request.POST.get('old_name', '').strip()[:100]
    new_name = request.POST.get('new_name', '').strip()[:100]
    if not old_name or not new_name:
        return JsonResponse({"error": "Both the current and new folder name are required."}, status=400)
    if old_name == new_name:
        return JsonResponse({"status": "success", "name": new_name})

    ChatSession.objects.filter(user=request.user, folder=old_name).update(folder=new_name)

    existing = Folder.objects.filter(user=request.user, name=new_name).first()
    old_folder = Folder.objects.filter(user=request.user, name=old_name).first()
    if existing:
        # Merge: keep the destination row, drop the source metadata row.
        if old_folder:
            old_folder.delete()
    elif old_folder:
        old_folder.name = new_name
        old_folder.save(update_fields=["name"])
    else:
        Folder.objects.get_or_create(user=request.user, name=new_name)
    return JsonResponse({"status": "success", "name": new_name})


@login_required
def delete_folder(request):
    """Delete a folder WITHOUT deleting any chats: unfiles every chat under
    it (folder='') and removes the metadata row. This is intentionally the
    only 'delete' in the folder workflow - there is deliberately no
    'delete folder and its chats', so a folder delete can never lose a
    conversation."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import Folder

    name = request.POST.get('name', '').strip()[:100]
    if not name:
        return JsonResponse({"error": "Folder name is required."}, status=400)
    unfiled = ChatSession.objects.filter(user=request.user, folder=name).update(folder='')
    Folder.objects.filter(user=request.user, name=name).delete()
    return JsonResponse({"status": "success", "unfiled": unfiled})


@login_required
def set_folder_color(request):
    """Change a folder's colour swatch. Upserts the metadata row so it works
    even on a legacy folder that only ever existed as a membership string."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    from chat.models import Folder

    name = request.POST.get('name', '').strip()[:100]
    color = request.POST.get('color', '').strip()
    if not name:
        return JsonResponse({"error": "Folder name is required."}, status=400)
    valid_colors = {c for c, _ in ChatSession.COLOR_CHOICES}
    if color not in valid_colors:
        return JsonResponse({"error": "Invalid color"}, status=400)
    folder, _ = Folder.objects.get_or_create(user=request.user, name=name)
    folder.color = color
    folder.save(update_fields=["color"])
    return JsonResponse({"status": "success", "name": name, "color": color})


@login_required
def set_session_color(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
    color = request.POST.get('color', '').strip()
    valid_colors = {c for c, _label in ChatSession.COLOR_CHOICES}
    if color not in valid_colors:
        return JsonResponse({"error": "Invalid color"}, status=400)
    session.color_label = color
    session.save(update_fields=["color_label"])
    return JsonResponse({"status": "success", "color_label": session.color_label})


@login_required
def search_chats(request):
    """Server-side search across session titles AND message content - the
    sidebar's plain text filter only ever matched titles already rendered in
    the DOM; this is what lets it also find a match buried inside an old
    conversation. Highlighting itself happens client-side (this just returns
    a snippet; wrapping the match in <mark> from a JSON string is simpler and
    safer than building HTML server-side)."""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({"results": []})

    results = []
    seen_session_ids = set()

    title_matches = ChatSession.objects.filter(user=request.user, title__icontains=query).order_by('-id')[:10]
    for s in title_matches:
        results.append({'session_id': s.id, 'title': s.title, 'snippet': None, 'match_type': 'title'})
        seen_session_ids.add(s.id)

    message_matches = (
        Message.objects.filter(session__user=request.user, content__icontains=query)
        .exclude(role='system').select_related('session').order_by('-created_at')[:30]
    )
    query_lower = query.lower()
    for m in message_matches:
        if m.session_id in seen_session_ids or len(results) >= 20:
            continue
        seen_session_ids.add(m.session_id)
        idx = m.content.lower().find(query_lower)
        start = max(0, idx - 40)
        end = min(len(m.content), idx + len(query) + 40)
        snippet = ('…' if start > 0 else '') + m.content[start:end] + ('…' if end < len(m.content) else '')
        results.append({
            'session_id': m.session_id, 'title': m.session.title,
            'snippet': snippet, 'match_type': 'message',
        })

    return JsonResponse({"results": results[:20], "query": query})


@login_required
def system_stats(request):
    try:
        gpu_usage = 0.0
        if GPUtil_AVAILABLE:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu_usage = gpus[0].load * 100
    except Exception:
        gpu_usage = 0.0
    data = {
        # interval=None (psutil's recommended mode for a repeatedly-polled
        # endpoint like this one): compares against the last call instead of
        # blocking the worker for interval*1000ms measuring a fresh sample -
        # matters a lot here since every open tab polls this every few
        # seconds, and a blocking sample ties up a whole worker each time.
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "gpu": round(gpu_usage, 1),
        "disk": psutil.disk_usage('/').percent
    }
    return JsonResponse(data)


@login_required
def upload_file(request):
    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return JsonResponse({"error": "No file uploaded"})

        safe_name, ext, error = _validate_attachment(uploaded_file)
        if error:
            return JsonResponse({"error": error}, status=400)

        result = _extract_attachment_text(uploaded_file, safe_name, ext)
        return JsonResponse({"analysis": result})
    return JsonResponse({"error": "Invalid request"})


@login_required
def update_model_session(request):
    if request.method == "GET":
        model_id = request.GET.get('model_id')
        session_id = request.GET.get('session_id')
        if model_id:
            request.session['selected_model'] = model_id
            if session_id and session_id not in ["null", "None", ""]:
                request.session[f'session_model_{session_id}'] = model_id
            request.session.modified = True
            return JsonResponse({
                "status": "success",
                "active_model": model_id
            })
    return JsonResponse({"status": "failed"}, status=400)


# ================= Email verification gating =================

# 30s anti-spam cooldown, applied here since allauth's own
# send_confirmation() has no built-in cooldown of its own.
VERIFICATION_EMAIL_RESEND_COOLDOWN_SECONDS = 30


@login_required
def resend_verification_email(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    if not verification_required():
        return JsonResponse({"status": "not_required"})

    from allauth.account.models import EmailAddress, EmailConfirmation
    email_address = (
        EmailAddress.objects.filter(user=request.user, primary=True).first()
        or EmailAddress.objects.filter(user=request.user).first()
    )
    if not email_address and request.user.email:
        # Accounts created before allauth's email-confirmation flow existed
        # (or created via Google) may have no EmailAddress row at all yet.
        email_address = EmailAddress.objects.create(
            user=request.user, email=request.user.email, primary=True, verified=False,
        )
    if not email_address:
        return JsonResponse({"error": "No email on file for this account."}, status=400)

    last_sent = (
        EmailConfirmation.objects.filter(email_address=email_address)
        .exclude(sent__isnull=True)
        .order_by("-sent")
        .first()
    )
    if last_sent:
        seconds_since = (timezone.now() - last_sent.sent).total_seconds()
        if seconds_since < VERIFICATION_EMAIL_RESEND_COOLDOWN_SECONDS:
            wait = int(VERIFICATION_EMAIL_RESEND_COOLDOWN_SECONDS - seconds_since)
            return JsonResponse({"error": f"Please wait {wait}s before requesting another email."}, status=429)

    email_address.send_confirmation(request)
    return JsonResponse({"status": "sent"})


@login_required
def verification_status(request):
    return JsonResponse({
        "verified": is_email_verified(request.user),
        "required": verification_required(),
    })


@login_required
def email_verified_success(request):
    """Landing page for ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL -
    reached right after a signed-in user's email confirmation link succeeds
    (see ACCOUNT_CONFIRM_EMAIL_ON_GET in settings.py). Not itself part of the
    verification decision (is_email_verified is the source of truth) - purely
    an acknowledgement page so confirming doesn't just silently drop the user
    back on chat home with no feedback that anything happened."""
    return render(request, 'account/email_verified_success.html')


# ================= Recovery-Code-based password reset =================
# Replaces the old emailed-OTP flow entirely - no email dependency at all
# for password recovery now. Local accounts only (see chat/models.py's
# RecoveryCode docstring): Google-only accounts (no usable local password)
# recover through Google itself, never through this flow.

def _recovery_eligible(user):
    return user is not None and user.has_usable_password() and RecoveryCode.objects.filter(user=user).exists()


def forgot_password(request):
    if request.method == "POST":
        identifier = request.POST.get("identifier", "").strip()
        user = None
        if identifier:
            user = User.objects.filter(username__iexact=identifier).first() \
                or User.objects.filter(email__iexact=identifier).first()
        if _recovery_eligible(user):
            request.session["recovery_reset_user_id"] = user.id
        # Same redirect regardless of whether the identifier matched an
        # account, or whether that account even has a recovery code (e.g. a
        # Google-only account) - otherwise this endpoint becomes a way to
        # enumerate registered users and how they signed up.
        return redirect("verify_recovery_code")
    return render(request, "account/forgot_password.html")


def verify_recovery_code(request):
    user_id = request.session.get("recovery_reset_user_id")

    if request.method == "POST":
        code = request.POST.get("code", "").strip().upper()
        user = User.objects.filter(id=user_id).first() if user_id else None
        recovery_code = RecoveryCode.objects.filter(user=user).first() if user else None
        if recovery_code and recovery_code.verify(code):
            request.session["recovery_verified_user_id"] = user_id
            del request.session["recovery_reset_user_id"]
            return redirect("reset_password_recovery")
        return render(request, "account/verify_recovery_code.html", {
            "error": "That recovery code is invalid.",
        })

    if not user_id:
        return redirect("forgot_password")
    return render(request, "account/verify_recovery_code.html")


def reset_password_recovery(request):
    user_id = request.session.get("recovery_verified_user_id")
    if not user_id:
        return redirect("forgot_password")

    if request.method == "POST":
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        if not password1 or password1 != password2:
            return render(request, "account/reset_password_recovery.html", {
                "error": "Those passwords don't match.",
            })
        try:
            validate_password(password1)
        except ValidationError as e:
            return render(request, "account/reset_password_recovery.html", {"error": " ".join(e.messages)})

        user = get_object_or_404(User, id=user_id)
        user.set_password(password1)
        user.save()
        # Bypasses allauth's own password-change flow entirely (a direct
        # set_password() call), so it doesn't fire allauth's password_
        # changed signal - chat/signals.py's record_password_changed relies
        # on that signal for the Timeline, so this path logs the same
        # SecurityEvent explicitly instead.
        SecurityEvent.objects.create(
            user=user, event_type="password_changed", severity="info",
            ip_address=client_ip(request), user_agent=raw_user_agent(request),
            detail="Password changed via recovery code",
        )
        # A used recovery code is retired the moment it's used to reset a
        # password - RecoveryCode.generate_for() overwrites the user's only
        # code, so the just-used one can never be replayed.
        _recovery_code, raw_code = RecoveryCode.generate_for(user)
        del request.session["recovery_verified_user_id"]
        request.session["pending_recovery_code"] = raw_code
        request.session["pending_recovery_code_next"] = "login"
        return redirect("recovery_code_display")

    return render(request, "account/reset_password_recovery.html")


@login_required
def regenerate_recovery_code(request):
    """Account Settings > Security's "Generate New Recovery Code" button.
    Overwrites (invalidates) whatever code existed before - a user only
    ever has one at a time, see RecoveryCode.generate_for()."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    if not request.user.has_usable_password():
        return JsonResponse({"error": "Google-linked accounts don't use recovery codes."}, status=400)
    _recovery_code, raw_code = RecoveryCode.generate_for(request.user)
    request.session["pending_recovery_code"] = raw_code
    request.session["pending_recovery_code_next"] = "settings"
    return JsonResponse({"status": "ok", "redirect": reverse("recovery_code_display")})


@login_required
def update_reaction(request):
    """Update reaction counts for messages via AJAX"""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        role = data.get('role')  # 'user' or 'assistant'
        reaction = data.get('reaction')
        
        if not all([message_id, role, reaction]):
            return JsonResponse({"error": "Missing required parameters"}, status=400)
        
        # Get the message object
        if role == 'user':
            # For user messages, we need to find by user_message_id in ChatMessage
            # But since we're using the new Message model, we'll look in Message
            message = Message.objects.get(id=message_id, session__user=request.user)
        elif role == 'assistant':
            message = Message.objects.get(id=message_id, session__user=request.user)
        else:
            return JsonResponse({"error": "Invalid role"}, status=400)
        
        # Initialize reactions in extra_data if not present
        if not message.extra_data:
            message.extra_data = {}
        if 'reactions' not in message.extra_data:
            message.extra_data['reactions'] = {}
        
        # Toggle the reaction
        current_count = message.extra_data['reactions'].get(reaction, 0)
        if reaction in message.extra_data['reactions']:
            # Reaction already exists, remove it (toggle off)
            new_count = current_count - 1
            if new_count <= 0:
                del message.extra_data['reactions'][reaction]
            else:
                message.extra_data['reactions'][reaction] = new_count
        else:
            # Reaction doesn't exist, add it (toggle on)
            message.extra_data['reactions'][reaction] = current_count + 1
        
        message.save()
        
        # Return the updated count
        new_count = message.extra_data['reactions'].get(reaction, 0)
        return JsonResponse({
            "success": True,
            "reaction": reaction,
            "count": new_count
        })
        
    except Message.DoesNotExist:
        return JsonResponse({"error": "Message not found"}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


_RECOVERY_CODE_NEXT_URLS = {"home": "home", "login": "account_login", "settings": "profile_settings"}


def recovery_code_display(request):
    """One-time display for a freshly generated recovery code - reached
    after local signup (chat/adapters.py's get_signup_redirect_url), after
    a successful password reset, or after regenerating from Account
    Settings > Security. The session key is popped (read once, discarded
    immediately) on the GET that renders the page, so refreshing or
    revisiting this URL afterwards can never show the same code twice -
    the "next" destination travels in a hidden form field instead, not the
    session, so the confirmation POST doesn't depend on session state that
    was already cleared."""
    if request.method == "POST":
        next_key = request.POST.get("next", "home")
        return redirect(_RECOVERY_CODE_NEXT_URLS.get(next_key, "home"))

    raw_code = request.session.pop("pending_recovery_code", None)
    next_key = request.session.pop("pending_recovery_code_next", "home")
    if not raw_code:
        return redirect("home")
    return render(request, "account/recovery_code_display.html", {
        "recovery_code": raw_code, "next_key": next_key,
    })


@login_required
@xframe_options_sameorigin
def serve_attachment(request, attachment_id):
    """Serves a stored attachment file with authentication, permission checks, and inline frame support."""
    try:
        attachment = get_object_or_404(MessageAttachment, id=attachment_id)
        if attachment.user != request.user and not (request.user.is_staff or request.user.is_superuser):
            return JsonResponse({"error": "Unauthorized"}, status=403)
        if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
            raise Http404("Attachment file not found")

        file_handle = attachment.file.open("rb")
        mime = attachment.mime_type or "application/octet-stream"
        response = FileResponse(file_handle, content_type=mime)
        
        force_download = request.GET.get("download") in ("1", "true", "yes")
        disposition = "attachment" if (force_download or attachment.file_type not in ("image", "pdf", "text", "code")) else "inline"
        
        response["Content-Disposition"] = f'{disposition}; filename="{attachment.original_name}"'
        response["X-Frame-Options"] = "SAMEORIGIN"
        return response
    except Exception as e:
        if isinstance(e, Http404):
            raise
        logger.warning(f"Failed to serve attachment {attachment_id}: {e}")
        raise Http404("Attachment not found")


@login_required
def attachment_content(request, attachment_id):
    """Returns readable text content or file metadata for modal viewer."""
    try:
        attachment = get_object_or_404(MessageAttachment, id=attachment_id)
        if attachment.user != request.user and not (request.user.is_staff or request.user.is_superuser):
            return JsonResponse({"status": "error", "message": "Unauthorized"}, status=403)
        if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
            return JsonResponse({"status": "error", "message": "Attachment file not found"}, status=404)

        if attachment.file_type == "image":
            return JsonResponse({
                "status": "success",
                "file_type": "image",
                "name": attachment.original_name,
                "size": attachment.file_size,
                "mime_type": attachment.mime_type,
                "url": f"/attachments/{attachment.id}/",
            })

        if attachment.file_type in ("text", "code", "pdf") or (attachment.mime_type and attachment.mime_type.startswith("text/")):
            # Read text (up to 500KB for preview/viewer)
            try:
                with attachment.file.open("rb") as f:
                    raw_bytes = f.read(500 * 1024)
                text = raw_bytes.decode("utf-8", errors="replace")
                truncated = attachment.file_size > len(raw_bytes)
                return JsonResponse({
                    "status": "success",
                    "file_type": attachment.file_type,
                    "name": attachment.original_name,
                    "size": attachment.file_size,
                    "mime_type": attachment.mime_type,
                    "content": text,
                    "truncated": truncated,
                    "url": f"/attachments/{attachment.id}/",
                })
            except Exception as e:
                return JsonResponse({
                    "status": "error",
                    "message": f"Could not read text content: {e}",
                    "url": f"/attachments/{attachment.id}/",
                })

        return JsonResponse({
            "status": "success",
            "file_type": "file",
            "name": attachment.original_name,
            "size": attachment.file_size,
            "mime_type": attachment.mime_type,
            "url": f"/attachments/{attachment.id}/",
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def agent_confirm_action(request):
    """Executes a confirmed sensitive agent tool on behalf of the user."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST request required."}, status=405)

    tool_name = request.POST.get("tool_name", "").strip()
    raw_args = request.POST.get("args", "{}")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except Exception:
        return JsonResponse({"success": False, "error": "Invalid arguments format."}, status=400)

    # Automatically set confirmed/overwrite flags for confirmed sensitive actions
    if isinstance(args, dict):
        if "confirmed" in args or tool_name in ["delete_file", "delete_folder"]:
            args["confirmed"] = True
        if "overwrite" in args or tool_name in ["write_file", "edit_file", "move_file", "copy_file"]:
            args["overwrite"] = True

    result = default_agent_controller.executor.execute_tool(tool_name, args)
    return JsonResponse(result.to_dict())


