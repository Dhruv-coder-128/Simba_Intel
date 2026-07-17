
import base64
import os
import time
import uuid
import zoneinfo
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
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

from chat.models import ChatSession, Message, UserProfile, UsageEvent, RecoveryCode, Broadcast, UserSession, SecurityEvent, FeatureFlag
from chat.services.ai_router import chat_stream, chat_stream_with_failover, vision as ai_vision
from chat.services.image_router import generate_image
from chat.services.memory import get_conversation_history, build_messages, messages_to_history_dicts, SYSTEM_PROMPT
from chat.services.conversation_memory import (
    build_context_messages, maybe_summarize_session, extract_and_store_facts, get_user_memory_context,
)
from chat.services.conversation_intelligence import (
    maybe_generate_smart_title, suggest_followups, find_related_conversations,
)
from chat.services.message_tree import (
    append_turn, build_display_messages, regenerate_assistant_reply, set_active_leaf, walk_chain_from,
)
from chat.services.model_registry import list_available_models, get_model_config, is_model_allowed_for_user
from chat.services.smart_router import resolve_model_id
from chat.services.usage import record_usage, record_failure, check_rate_limit, check_daily_limit
from chat.services.verification import is_email_verified, verification_required
from chat.utils.logger import SimbaLogger
from chat.utils.request_info import client_ip, raw_user_agent

from chat.file_analyzer import analyze_file

# Loaded once at import time (not per-request) - the same sorted list backs
# both the Settings > General timezone <select> and server-side validation
# in profile_settings/set_timezone, so a submitted value can never diverge
# from what the dropdown actually offered.
AVAILABLE_TIMEZONES = sorted(zoneinfo.available_timezones())


logger = SimbaLogger()

User = get_user_model()

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".csv", ".txt"} | ALLOWED_IMAGE_EXTENSIONS
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


def _validate_attachment(attachment):
    """Returns (safe_name, ext, error_message_or_None)."""
    if attachment.size > MAX_UPLOAD_SIZE_BYTES:
        return None, None, "File too large (max 10MB)"
    safe_name = os.path.basename(attachment.name)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return None, None, "Unsupported file type"
    return safe_name, ext, None


def _extract_attachment_text(attachment, safe_name, ext):
    """Save an uploaded file transiently, run it through file_analyzer, then delete it."""
    save_dir = os.path.join(settings.BASE_DIR, "uploads")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{uuid.uuid4().hex}{ext}")
    with open(save_path, "wb+") as f:
        for chunk in attachment.chunks():
            f.write(chunk)
    try:
        return analyze_file(save_path)
    finally:
        try:
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


def _is_search_query(query: str) -> bool:
    search_keywords = ["latest", "today", "news", "search", "current", "price", "weather", "now", "recent", "stock", "market"]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in search_keywords)


def _stream_with_failover(model_id, messages, on_usage):
    """Shared by every stream_generator (ask_ai, regenerate_message,
    edit_message, continue_message) - wraps chat_stream_with_failover and
    tracks which model actually ends up serving the request. Returns
    (token_generator, serving) - serving['model_id'] is only reliable once
    the generator has been fully consumed (it flips the moment a switch
    happens, which - by chat_stream_with_failover's own contract - is always
    before the first token is yielded).

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

    def on_switch(new_model_id):
        serving["model_id"] = new_model_id

    def token_generator():
        for i, token in enumerate(chat_stream_with_failover(
            model_id, messages, on_switch=on_switch, on_usage=on_usage,
        )):
            if i == 0 and serving["model_id"] != model_id:
                switched_cfg = get_model_config(serving["model_id"])
                yield (f"_(Switched to {switched_cfg.display_name} after a temporary provider issue)_\n\n", True)
            yield (token, False)

    return token_generator(), serving


@login_required
def chat_home(request):
    profile = UserProfile.get_or_create_for(request.user)

    view_mode = request.GET.get('view', 'active')
    folder_filter = request.GET.get('folder', '').strip()

    base_qs = ChatSession.objects.filter(user=request.user, is_archived=(view_mode == 'archived'))
    if folder_filter:
        base_qs = base_qs.filter(folder=folder_filter)
    sessions = list(base_qs.order_by('-is_pinned', '-id'))

    # Pinned/Favorites are their own sections regardless of age; everything
    # else is grouped into relative-date buckets (Today/Yesterday/Last 7
    # Days/Last 30 Days/Older) computed here rather than in the template -
    # Django templates have no built-in "group by relative date" filter, and
    # a custom templatetag for a one-off grouping isn't worth the indirection.
    pinned_sessions = [s for s in sessions if s.is_pinned]
    favorite_sessions = [s for s in sessions if s.is_favorite and not s.is_pinned]
    other_sessions = [s for s in sessions if not s.is_pinned and not s.is_favorite]

    today = timezone.localdate()
    grouped_sessions = {'today': [], 'yesterday': [], 'week': [], 'month': [], 'older': []}
    for s in other_sessions:
        session_date = timezone.localtime(s.created_at).date()
        if session_date == today:
            grouped_sessions['today'].append(s)
        elif session_date == today - timedelta(days=1):
            grouped_sessions['yesterday'].append(s)
        elif session_date >= today - timedelta(days=7):
            grouped_sessions['week'].append(s)
        elif session_date >= today - timedelta(days=30):
            grouped_sessions['month'].append(s)
        else:
            grouped_sessions['older'].append(s)

    # Folders shown in the sidebar = the union of (a) folder names actually
    # in use by a non-archived chat and (b) empty folders that only exist as
    # a metadata row (created but nothing filed yet). Each carries its colour
    # (from the Folder metadata row, default '' when none) and a live chat
    # count, so the manager can show both without a query per folder.
    from chat.models import Folder as FolderModel
    from django.db.models import Count as _Count

    used_counts = dict(
        ChatSession.objects.filter(user=request.user, is_archived=False)
        .exclude(folder='').values_list('folder').annotate(n=_Count('id'))
    )
    folder_colors = dict(
        FolderModel.objects.filter(user=request.user).values_list('name', 'color')
    )
    folder_names = sorted(set(used_counts) | set(folder_colors), key=str.lower)
    folders = [
        {'name': name, 'color': folder_colors.get(name, ''), 'count': used_counts.get(name, 0)}
        for name in folder_names
    ]

    session_id = request.GET.get('session')
    messages = []
    current_session = None
    if session_id and session_id not in ["null", "None", ""]:
        try:
            current_session = get_object_or_404(ChatSession, id=session_id, user=request.user)
            messages = build_display_messages(current_session)
        except Exception:
            current_session = None
    selected_model = request.session.get("selected_model", profile.default_model)
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
        'grouped_sessions': grouped_sessions,
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
        'email_verified': verified,
        'user_sessions': UserSession.objects.filter(user=request.user).order_by('-created_at'),
        'current_session_key': request.session.session_key,
        'recent_logins': SecurityEvent.objects.filter(user=request.user, event_type='login').order_by('-created_at')[:10],
        'google_account': SocialAccount.objects.filter(user=request.user, provider='google').first(),
        'memory_fact_count': UserFact.objects.filter(user=request.user).count(),
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
        user_query = request.POST.get('query', '').strip()
        model_id = request.POST.get('model_id', 'cyber-max')
        session_id = request.POST.get('session_id')
        attachments = request.FILES.getlist('attachment')
        # Session remembers the literal "auto" choice (so Auto mode stays
        # selected across reloads, re-routing fresh on every future message)
        # - model_id itself gets resolved to a concrete, real model right
        # below, so every line after this block can keep treating it as one
        # exactly like before Smart Routing existed.
        request.session["selected_model"] = model_id
        request.session.modified = True
        profile = UserProfile.get_or_create_for(request.user)
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
                session = ChatSession.objects.create(user=request.user, title=session_title)
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

                    allowed, limit_message = check_daily_limit(request.user, "vision")
                    if not allowed:
                        limit_response = JsonResponse({"type": "error", "message": limit_message}, status=429)
                        limit_response["X-Session-ID"] = str(session.id)
                        return limit_response

                    # True vision: send every image straight to a vision-capable model
                    # in a single multi-image message.
                    try:
                        text_parts = []
                        for att, safe_name, ext in doc_files:
                            extracted = _extract_attachment_text(att, safe_name, ext)
                            text_parts.append(f"--- Attached file: {safe_name} ---\n{extracted}\n--- End attachment ---")
                        text_parts.append(user_query or (
                            "Describe this image." if len(image_files) == 1 else "Describe these images."
                        ))

                        content = [{"type": "text", "text": "\n\n".join(text_parts)}]
                        image_previews = []
                        filenames = []
                        for att, safe_name, ext in image_files:
                            image_bytes = att.read()
                            mime = IMAGE_MIME_TYPES.get(ext, "image/jpeg")
                            data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
                            content.append({"type": "image_url", "image_url": {"url": data_uri}})
                            image_previews.append(data_uri)
                            filenames.append(safe_name)

                        vision_messages = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": content}
                        ]
                        captured_usage = {}
                        start_time = time.time()
                        vision_text = ai_vision(model_id, vision_messages, on_usage=captured_usage.update)
                        latency = round(time.time() - start_time, 2)

                        display_query = user_query or f"[{len(image_files)} image(s): {', '.join(filenames)}]"
                        _user_msg, assistant_msg = append_turn(
                            session, display_query, vision_text,
                            assistant_extra_data={
                                "type": "vision",
                                "filenames": filenames,
                                "image_previews": image_previews,
                                # kept for backward compatibility with older rendered history
                                "filename": filenames[0],
                                "image_preview": image_previews[0],
                            },
                            latency=latency,
                        )
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
                    for att, safe_name, ext in validated:
                        extracted = _extract_attachment_text(att, safe_name, ext)
                        extracted_blocks.append(f"--- Attached file: {safe_name} ---\n{extracted}\n--- End attachment ---")
                    context_block = "\n\n".join(extracted_blocks)
                    user_query = f"{context_block}\n\n{user_query}" if user_query else context_block

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

                allowed, limit_message = check_daily_limit(request.user, "image")
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
                    _user_msg, assistant_msg = append_turn(
                        session, user_query, "",
                        assistant_extra_data={
                            "type": "image",
                            "image_url": result["image_url"],
                            "model_used": result["model_used"],
                            "prompt": result["prompt"],
                            "width": result["width"],
                            "height": result["height"],
                            "generation_time": result.get("generation_time", 0)
                        },
                        latency=result.get("generation_time", 0),
                    )
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

            allowed, limit_message = check_daily_limit(request.user, "chat")
            if not allowed:
                limit_response = JsonResponse({"type": "error", "message": limit_message}, status=429)
                limit_response["X-Session-ID"] = str(session.id)
                return limit_response

            chat_system_prompt = SYSTEM_PROMPT
            if profile.memory_enabled:
                memory_context = get_user_memory_context(request.user)
                if memory_context:
                    chat_system_prompt = f"{SYSTEM_PROMPT}\n\n{memory_context}"
            messages = build_context_messages(session, user_query, chat_system_prompt)
            if FeatureFlag.is_enabled('web_search', default=True) and _is_search_query(user_query):
                search_results = _get_tavily_search(user_query)
                if search_results:
                    context_str = "\n\n".join([f"- {result['title']}: {result['content']}" for result in search_results])
                    augmented_query = f"{user_query}\n\nRelevant search results:\n{context_str}"
                    messages[-1]['content'] = augmented_query
            
            def stream_generator():
                full_response = ""
                start_time = time.time()
                captured_usage = {}
                token_gen, serving = _stream_with_failover(model_id, messages, captured_usage.update)
                try:
                    for token, is_notice in token_gen:
                        if not is_notice:
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
                    yield f"\n\nError: {str(e)}"
                else:
                    latency = round(time.time() - start_time, 2)
                    actual_config = get_model_config(serving["model_id"])
                    if full_response.strip():
                        is_first_turn = not session.thread.exists()
                        append_turn(session, user_query, full_response, latency=latency)
                        record_usage(
                            request.user, session, actual_config.provider, serving["model_id"], "chat",
                            prompt_text=user_query, completion_text=full_response,
                            captured_usage=captured_usage, latency=latency,
                        )
                        # Both best-effort and non-blocking to the response
                        # already sent above - a failure here never affects
                        # the reply the user just received (see their own
                        # docstrings/try-excepts in conversation_memory.py
                        # and conversation_intelligence.py).
                        if is_first_turn:
                            maybe_generate_smart_title(session, user_query, full_response)
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
    rather than it running automatically on every single turn."""
    session = get_object_or_404(ChatSession, id=session_id, user=request.user)
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
    sibling_ids = list(
        Message.objects.filter(session=msg.session, parent_id=msg.parent_id, role=msg.role)
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

    old_msg = get_object_or_404(Message, id=message_id, role='assistant', session__user=request.user)
    session = old_msg.session
    model_id = request.POST.get('model_id') or request.session.get('selected_model', 'cyber-max')
    user_query = old_msg.parent.content if old_msg.parent else ""
    if model_id.lower() == "auto":
        routing_profile = UserProfile.get_or_create_for(request.user)
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
        captured_usage = {}
        token_gen, serving = _stream_with_failover(model_id, messages, captured_usage.update)
        try:
            for token, is_notice in token_gen:
                if not is_notice:
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
            yield f"\n\nError: {str(e)}"
        else:
            latency = round(time.time() - start_time, 2)
            actual_config = get_model_config(serving["model_id"])
            if full_response.strip():
                regenerate_assistant_reply(old_msg, full_response, latency=latency)
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

    old_msg = get_object_or_404(Message, id=message_id, role='user', session__user=request.user)
    session = old_msg.session
    new_content = request.POST.get('content', '').strip()
    if not new_content:
        return JsonResponse({"response": "Query cannot be empty"}, status=400)

    model_id = request.POST.get('model_id') or request.session.get('selected_model', 'cyber-max')
    if model_id.lower() == "auto":
        routing_profile = UserProfile.get_or_create_for(request.user)
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
        captured_usage = {}
        token_gen, serving = _stream_with_failover(model_id, messages, captured_usage.update)
        try:
            for token, is_notice in token_gen:
                if not is_notice:
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
            yield f"\n\nError: {str(e)}"
        else:
            latency = round(time.time() - start_time, 2)
            actual_config = get_model_config(serving["model_id"])
            if full_response.strip():
                append_turn(session, new_content, full_response, latency=latency, parent=old_msg.parent)
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

    msg = get_object_or_404(Message, id=message_id, session__user=request.user)
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
    msg = get_object_or_404(Message, id=message_id, session__user=request.user)
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

    old_msg = get_object_or_404(Message, id=message_id, role='assistant', session__user=request.user)
    session = old_msg.session
    model_id = request.POST.get('model_id') or request.session.get('selected_model', 'cyber-max')
    user_query = old_msg.parent.content if old_msg.parent else ""
    if model_id.lower() == "auto":
        routing_profile = UserProfile.get_or_create_for(request.user)
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
        captured_usage = {}
        token_gen, serving = _stream_with_failover(model_id, messages, captured_usage.update)
        try:
            for token, is_notice in token_gen:
                if not is_notice:
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
            yield f"\n\nError: {str(e)}"
        else:
            latency = round(time.time() - start_time, 2)
            actual_config = get_model_config(serving["model_id"])
            if full_response.strip():
                old_msg.content = old_msg.content + full_response
                old_msg.latency = (old_msg.latency or 0) + latency
                old_msg.save(update_fields=["content", "latency"])
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
        session.save()
        return JsonResponse({"status": "success"})


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
    return JsonResponse({"status": "success", "session_id": new_session.id})


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
        count = sessions.count()
        sessions.delete()
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
        if model_id:
            request.session['selected_model'] = model_id
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
