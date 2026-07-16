
import base64
import os
import time
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.utils import timezone
import psutil

try:
    import GPUtil
    GPUtil_AVAILABLE = True
except ImportError:
    GPUtil_AVAILABLE = False

from chat.models import ChatSession, Message, UserProfile, UsageEvent, PasswordResetOTP, Broadcast, UserSession, SecurityEvent, FeatureFlag
from chat.services.ai_router import chat_stream, vision as ai_vision
from chat.services.image_router import generate_image
from chat.services.memory import get_conversation_history, build_messages, messages_to_history_dicts, SYSTEM_PROMPT
from chat.services.message_tree import (
    append_turn, build_display_messages, regenerate_assistant_reply, set_active_leaf, walk_chain_from,
)
from chat.services.model_registry import list_available_models, get_model_config
from chat.services.usage import record_usage, check_rate_limit, check_daily_limit
from chat.services.email import send_otp_email as send_otp_email_hardened
from chat.services.verification import is_email_verified, verification_required
from chat.utils.logger import SimbaLogger

from chat.file_analyzer import analyze_file


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


@login_required
def chat_home(request):
    profile = UserProfile.get_or_create_for(request.user)
    sessions = ChatSession.objects.filter(user=request.user).order_by('-is_pinned', '-id')
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
                'email_verified': False,
            }, status=403)
        display_name = request.POST.get('display_name', '').strip()[:100]
        default_model = request.POST.get('default_model', '').strip()
        theme = request.POST.get('theme', '').strip()

        profile.display_name = display_name
        if default_model in valid_model_ids:
            profile.default_model = default_model
        if theme in valid_themes:
            profile.theme = theme
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
            return redirect(f'/?session={next_session_id}')
        return redirect('home')

    from allauth.socialaccount.models import SocialAccount

    return render(request, 'profile.html', {
        'profile': profile,
        'models': list_available_models(),
        'theme_choices': UserProfile.THEME_CHOICES,
        'email_verified': verified,
        'user_sessions': UserSession.objects.filter(user=request.user).order_by('-created_at'),
        'current_session_key': request.session.session_key,
        'recent_logins': SecurityEvent.objects.filter(user=request.user, event_type='login').order_by('-created_at')[:10],
        'google_account': SocialAccount.objects.filter(user=request.user, provider='google').first(),
    })


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
def analytics_dashboard(request):
    """Phase 5 (expanded): pure read-side view over UsageEvent - no writes
    happen here, so it's safe to hit as often as the user likes.

    Deliberately does NOT report success/error rate, a top-prompts list, or
    a "files processed" count - none of those are tracked anywhere in the
    data model today (UsageEvent rows are only ever created on a successful
    call, and no prompt text or file-processing event is stored), so faking
    them would mean showing invented numbers. Every figure below is a real
    aggregate over what's actually recorded.
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

    events = UsageEvent.objects.filter(user=request.user)

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
        'requests_today': events.filter(created_at__date=today).count(),
        'requests_this_week': events.filter(created_at__date__gte=today - timedelta(days=6)).count(),
        'requests_this_month': events.filter(created_at__year=today.year, created_at__month=today.month).count(),
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
        request.session["selected_model"] = model_id
        request.session.modified = True
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
                            error=str(e)
                        )
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
                        error=str(e)
                    )
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

            history = get_conversation_history(session)
            messages = build_messages(user_query, history)
            if _is_search_query(user_query):
                search_results = _get_tavily_search(user_query)
                if search_results:
                    context_str = "\n\n".join([f"- {result['title']}: {result['content']}" for result in search_results])
                    augmented_query = f"{user_query}\n\nRelevant search results:\n{context_str}"
                    messages[-1]['content'] = augmented_query
            
            def stream_generator():
                full_response = ""
                start_time = time.time()
                captured_usage = {}
                try:
                    for token in chat_stream(model_id, messages, on_usage=captured_usage.update):
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
                    yield f"\n\nError: {str(e)}"
                else:
                    latency = round(time.time() - start_time, 2)
                    if full_response.strip():
                        append_turn(session, user_query, full_response, latency=latency)
                        record_usage(
                            request.user, session, model_config.provider, model_id, "chat",
                            prompt_text=user_query, completion_text=full_response,
                            captured_usage=captured_usage, latency=latency,
                        )
                    logger.log_request(
                        provider=model_config.provider,
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

    try:
        model_config = get_model_config(model_id)
    except KeyError:
        return JsonResponse({"type": "error", "message": "Invalid model selection."}, status=400)

    user_query = old_msg.parent.content if old_msg.parent else ""
    # Context up to (but excluding) the user turn this reply answers - it
    # gets appended separately by build_messages, same as the normal send flow.
    history_chain = walk_chain_from(old_msg.parent)[:-1]
    history = messages_to_history_dicts(history_chain)
    messages = build_messages(user_query, history)

    def stream_generator():
        full_response = ""
        start_time = time.time()
        captured_usage = {}
        try:
            for token in chat_stream(model_id, messages, on_usage=captured_usage.update):
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
            yield f"\n\nError: {str(e)}"
        else:
            latency = round(time.time() - start_time, 2)
            if full_response.strip():
                regenerate_assistant_reply(old_msg, full_response, latency=latency)
                record_usage(
                    request.user, session, model_config.provider, model_id, "chat",
                    prompt_text=user_query, completion_text=full_response,
                    captured_usage=captured_usage, latency=latency,
                )
            logger.log_request(
                provider=model_config.provider,
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
        try:
            for token in chat_stream(model_id, messages, on_usage=captured_usage.update):
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
            yield f"\n\nError: {str(e)}"
        else:
            latency = round(time.time() - start_time, 2)
            if full_response.strip():
                append_turn(session, new_content, full_response, latency=latency, parent=old_msg.parent)
                record_usage(
                    request.user, session, model_config.provider, model_id, "chat",
                    prompt_text=new_content, completion_text=full_response,
                    captured_usage=captured_usage, latency=latency,
                )
            logger.log_request(
                provider=model_config.provider,
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

# Matches PasswordResetOTP.OTP_RESEND_COOLDOWN_SECONDS - same anti-spam
# rationale, applied here since allauth's own send_confirmation() has no
# built-in cooldown of its own.
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


# ================= OTP-based password reset =================
# A separate, additional path from django-allauth's own (link-based) reset
# flow, which is untouched and still reachable at its original URL - this
# exists because the requested UX is specifically Forgot Password -> Email
# OTP -> Verify OTP -> New Password -> Login.

def _send_otp_email(user, otp):
    """Thin wrapper kept under its original name/signature (admin_views.py
    imports it directly) - all the actual work, including the timeout/
    exception hardening that fixed the production SMTP hang, lives in
    chat/services/email.py. Returns the EmailSendResult rather than raising,
    so every call site below decides for itself how to degrade."""
    return send_otp_email_hardened(user, otp)


def forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user:
            otp = PasswordResetOTP.generate_for(user)
            result = _send_otp_email(user, otp)
            if not result.success:
                # Deliberately NOT surfaced differently to the client than
                # the success path below - same anti-enumeration reasoning
                # as before (a distinguishable response here would leak
                # "this email exists but sending failed" vs "no such
                # email"). The failure is fully logged server-side by
                # send_otp_email_hardened; the user just doesn't get a code
                # that was never actually sent, and can use "resend" (which
                # DOES report failures) once the underlying issue clears.
                pass
            request.session["otp_reset_user_id"] = user.id
            request.session["otp_reset_email"] = user.email
        # Same response whether or not the email matched a real account -
        # otherwise this endpoint becomes a way to enumerate registered users.
        return redirect("verify_otp")
    return render(request, "account/forgot_password.html")


def verify_otp(request):
    user_id = request.session.get("otp_reset_user_id")
    masked_email = request.session.get("otp_reset_email", "")

    if request.method == "POST":
        if not user_id:
            return render(request, "account/verify_otp.html", {
                "error": "Your session expired. Please request a new code.",
            })
        code = request.POST.get("code", "").strip()
        otp = PasswordResetOTP.objects.filter(user_id=user_id, code=code).order_by("-created_at").first()
        if otp and otp.is_valid():
            otp.used = True
            otp.save(update_fields=["used"])
            request.session["otp_verified_user_id"] = user_id
            del request.session["otp_reset_user_id"]
            return redirect("reset_password_otp")
        return render(request, "account/verify_otp.html", {
            "error": "That code is invalid or has expired.", "masked_email": masked_email,
        })

    if not user_id:
        return redirect("forgot_password")
    return render(request, "account/verify_otp.html", {"masked_email": masked_email})


def resend_otp(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    user_id = request.session.get("otp_reset_user_id")
    user = User.objects.filter(id=user_id).first() if user_id else None
    if not user:
        return JsonResponse({"error": "Your session expired. Please start over."}, status=400)

    last_otp = PasswordResetOTP.objects.filter(user=user).order_by("-created_at").first()
    if last_otp:
        seconds_since = (timezone.now() - last_otp.created_at).total_seconds()
        if seconds_since < PasswordResetOTP.OTP_RESEND_COOLDOWN_SECONDS:
            wait = int(PasswordResetOTP.OTP_RESEND_COOLDOWN_SECONDS - seconds_since)
            return JsonResponse({"error": f"Please wait {wait}s before requesting another code."}, status=429)

    otp = PasswordResetOTP.generate_for(user)
    result = _send_otp_email(user, otp)
    if not result.success:
        # This endpoint is only reachable by someone who already passed the
        # "does this email exist" gate in forgot_password, so there's no
        # enumeration risk in reporting failure honestly here (unlike
        # forgot_password itself) - the user needs to know a code wasn't
        # actually sent rather than wait indefinitely for one that never
        # arrives.
        return JsonResponse({"error": result.error}, status=503)
    return JsonResponse({"status": "sent"})


def reset_password_otp(request):
    user_id = request.session.get("otp_verified_user_id")
    if not user_id:
        return redirect("forgot_password")

    if request.method == "POST":
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        if not password1 or password1 != password2:
            return render(request, "account/reset_password_otp.html", {
                "error": "Those passwords don't match.",
            })
        try:
            validate_password(password1)
        except ValidationError as e:
            return render(request, "account/reset_password_otp.html", {"error": " ".join(e.messages)})

        user = get_object_or_404(User, id=user_id)
        user.set_password(password1)
        user.save()
        del request.session["otp_verified_user_id"]
        messages.success(request, "Your password has been reset. Please log in.")
        return redirect("account_login")

    return render(request, "account/reset_password_otp.html")
