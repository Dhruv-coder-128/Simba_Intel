"""Custom Super Admin Console - deliberately NOT django.contrib.admin.
Every view here is role-gated via @require_role(Role.ADMIN) (chat/
permissions.py) and every mutating action is written to AdminAuditLog. Kept
in its own module rather than chat/views.py (already 1000+ lines covering
the actual product) so the two surfaces - user-facing app vs. operator
console - stay easy to tell apart.
"""
import csv
import json
import time
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db import connection, models as db_models, transaction
from django.db.models import Avg, Count, Prefetch, Sum, Q
from django.db.models.functions import ExtractHour, TruncDate
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from chat.models import (
    AdminAuditLog, Broadcast, ChatSession, FailedLoginAttempt,
    FeatureFlag, Message, Role, SecurityEvent, UsageEvent, UserNote, UserProfile, UserSession,
)
from chat.permissions import (
    can_act_on_target, has_role_at_least, is_owner, require_role, sync_django_flags,
)
from chat.services.model_registry import MODEL_REGISTRY, list_available_models
from chat.utils.device import parse_client_info
from chat.utils.request_info import client_ip, raw_user_agent

User = get_user_model()

# Every admin-console view needs both: logged in (so an anonymous request
# gets sent to the login page, not a bare 403) and role >= Admin (so an
# authenticated but under-privileged user gets a real 403, not a redirect
# loop). login_required must run first - it's the outer decorator. Kept
# under its original name (rather than renaming every @superuser_required
# below) so this is a permission-mechanism swap, not a routing change.
def superuser_required(view_func):
    return login_required(require_role(Role.ADMIN)(view_func))


def _log(request, action, target_user=None, detail="", success=True):
    browser, _device, _os = parse_client_info(raw_user_agent(request))
    AdminAuditLog.objects.create(
        actor=request.user, action=action, target_user=target_user, detail=detail,
        ip_address=client_ip(request), browser=browser, success=success,
    )


# Cell values starting with any of these are interpreted as formulas by
# Excel/LibreOffice/Google Sheets when the CSV is opened, not as plain text.
_CSV_FORMULA_TRIGGER_CHARS = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe_row(row):
    """Neutralizes CSV/spreadsheet formula injection (OWASP CSV Injection)
    before writing a data row: Django's default username validator allows a
    username to start with +, -, or @ (only = is disallowed), so a
    self-chosen username - or free-text fields like an audit log's detail
    or a security event's detail - can end up starting with a formula
    trigger character undetected until an operator opens the exported CSV
    in a spreadsheet app. Prefixing such a value with a single quote is the
    standard mitigation: it forces the cell to be read as text while
    leaving every normal value completely unchanged."""
    return [
        "'" + v if isinstance(v, str) and v.startswith(_CSV_FORMULA_TRIGGER_CHARS) else v
        for v in row
    ]


def _force_logout_user(user):
    """Django keeps no per-user session index, so this decodes every active
    session to find the ones belonging to this user - O(active sessions),
    acceptable at this project's current scale. Revisit (e.g. a
    UserSession tracking model updated at login) before this becomes the
    bottleneck at real scale."""
    killed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        if str(data.get('_auth_user_id')) == str(user.id):
            session.delete()
            killed += 1
    return killed


# ================= Dashboard =================

@superuser_required
def admin_dashboard(request):
    from allauth.account.models import EmailAddress

    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    banned_users = UserProfile.objects.filter(is_banned=True).count()
    # Role-based, not is_staff - is_staff is kept in sync as a side effect
    # of role changes (chat/permissions.py's sync_django_flags) purely for
    # Django admin compatibility, but is never itself the source of truth.
    staff_users = UserProfile.objects.filter(
        role__in=[Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR]
    ).count()

    verified_users = EmailAddress.objects.filter(verified=True).values('user').distinct().count()
    unverified_users = total_users - verified_users

    online_cutoff = timezone.now() - timedelta(minutes=5)
    online_users = SecurityEvent.objects.filter(
        event_type="login", created_at__gte=online_cutoff
    ).values('user').distinct().count()

    # Real Daily Active Users - distinct users with EITHER a login OR any AI
    # usage today, not a re-display of "Online Now" (~5min window). Two
    # small distinct-count queries unioned in Python (a SQL UNION across
    # different source tables isn't worth the complexity here).
    today_start = timezone.make_aware(timezone.datetime.combine(timezone.localdate(), timezone.datetime.min.time()))
    dau_login_ids = set(SecurityEvent.objects.filter(
        event_type="login", created_at__gte=today_start
    ).values_list('user_id', flat=True))
    dau_usage_ids = set(UsageEvent.objects.filter(
        created_at__gte=today_start
    ).values_list('user_id', flat=True))
    daily_active_users = len(dau_login_ids | dau_usage_ids)

    # A UserSession row alone doesn't mean the session is still valid -
    # Django's own Session table is the source of truth for expiry, so this
    # cross-references both rather than trusting UserSession row count alone
    # (which would over-count sessions that expired without an explicit
    # logout - Django only prunes those via the periodic `clearsessions`
    # management command, not automatically).
    live_session_keys = Session.objects.filter(expire_date__gte=timezone.now()).values_list('session_key', flat=True)
    active_sessions = UserSession.objects.filter(session_key__in=live_session_keys).count()

    new_today = User.objects.filter(date_joined__date=timezone.localdate()).count()
    new_this_week = User.objects.filter(date_joined__date__gte=timezone.localdate() - timedelta(days=6)).count()

    total_sessions = ChatSession.objects.count()
    total_messages = Message.objects.count()

    usage_totals = UsageEvent.objects.aggregate(
        total_requests=Count('id'),
        total_cost=Sum('estimated_cost_usd'),
        total_tokens=Sum(db_models.F('prompt_tokens') + db_models.F('completion_tokens')),
        avg_latency=Avg('latency'),
    )
    images_generated = UsageEvent.objects.filter(event_type='image').count()
    vision_calls = UsageEvent.objects.filter(event_type='vision').count()
    chat_requests = UsageEvent.objects.filter(event_type='chat').count()

    monthly_cutoff = timezone.now() - timedelta(days=30)
    monthly_active_users = UsageEvent.objects.filter(
        created_at__gte=monthly_cutoff
    ).values('user').distinct().count()

    # Provider Usage - internal-only by design (never rendered on any
    # user-facing page, only here in the admin console) - raw provider
    # names are fine to show an operator, just never a customer.
    by_provider = [
        {'provider': row['provider'], 'requests': row['requests'], 'cost': float(row['cost'] or 0)}
        for row in (
            UsageEvent.objects.values('provider')
            .annotate(requests=Count('id'), cost=Sum('estimated_cost_usd'))
            .order_by('-requests')
        )
    ]
    by_model = [
        {
            'model_id': row['model_id'],
            'display_name': (MODEL_REGISTRY[row['model_id']].display_name if row['model_id'] in MODEL_REGISTRY else row['model_id']),
            'requests': row['requests'],
        }
        for row in UsageEvent.objects.values('model_id').annotate(requests=Count('id')).order_by('-requests')[:8]
    ]

    # Single grouped query instead of 7 separate .count() calls, one per day.
    today = timezone.localdate()
    signup_window_start = today - timedelta(days=6)
    signup_counts = dict(
        User.objects.filter(date_joined__date__gte=signup_window_start)
        .annotate(day=TruncDate('date_joined'))
        .values('day')
        .annotate(count=Count('id'))
        .values_list('day', 'count')
    )
    daily_signups = [
        {
            'date': (today - timedelta(days=i)).isoformat(),
            'count': signup_counts.get(today - timedelta(days=i), 0),
        }
        for i in range(6, -1, -1)
    ]

    # Admin-wide (all users) daily series for the last 14 days - requests,
    # cost, tokens, and login activity all in one pass each, not one query
    # per day (14 separate .count() calls would otherwise be needed).
    chart_window_start = today - timedelta(days=13)
    usage_by_day = {
        row['day']: row
        for row in (
            UsageEvent.objects.filter(created_at__date__gte=chart_window_start)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(
                requests=Count('id'), cost=Sum('estimated_cost_usd'),
                tokens=Sum(db_models.F('prompt_tokens') + db_models.F('completion_tokens')),
            )
        )
    }
    _login_days, logins_by_day = _daily_login_counts(14)
    daily_requests, daily_cost, daily_tokens, login_activity = [], [], [], []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        row = usage_by_day.get(day)
        date_str = day.isoformat()
        daily_requests.append({'date': date_str, 'count': row['requests'] if row else 0})
        daily_cost.append({'date': date_str, 'cost': float(row['cost']) if row and row['cost'] else 0.0})
        daily_tokens.append({'date': date_str, 'tokens': row['tokens'] if row and row['tokens'] else 0})
        login_activity.append({'date': date_str, 'count': logins_by_day.get(day, 0)})

    recent_errors = SecurityEvent.objects.filter(
        severity__in=['warning', 'critical']
    ).select_related('user').order_by('-created_at')[:10]
    recent_audit = AdminAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')[:10]

    # Peak usage hours - single grouped query over the last 30 days, all
    # hour buckets present (0 for hours with no traffic) so the chart never
    # has to guess at missing labels.
    peak_hours_cutoff = timezone.now() - timedelta(days=30)
    peak_hours_counts = dict(
        UsageEvent.objects.filter(created_at__gte=peak_hours_cutoff)
        .annotate(hour=ExtractHour('created_at'))
        .values('hour').annotate(count=Count('id')).values_list('hour', 'count')
    )
    peak_hours = [{'hour': h, 'count': peak_hours_counts.get(h, 0)} for h in range(24)]

    most_active_users = list(
        UsageEvent.objects.filter(created_at__gte=monthly_cutoff)
        .values('user_id', 'user__username')
        .annotate(requests=Count('id'))
        .order_by('-requests')[:10]
    )

    feature_flags_glance = list(FeatureFlag.objects.order_by('key')[:8])

    db_stats = {
        'users': total_users,
        'chat_sessions': total_sessions,
        'messages': total_messages,
        'usage_events': usage_totals['total_requests'] or 0,
        'security_events': SecurityEvent.objects.count(),
        'audit_log_entries': AdminAuditLog.objects.count(),
    }

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'banned_users': banned_users,
        'staff_users': staff_users,
        'verified_users': verified_users,
        'unverified_users': unverified_users,
        'online_users': online_users,
        'daily_active_users': daily_active_users,
        'active_sessions': active_sessions,
        'new_today': new_today,
        'new_this_week': new_this_week,
        'monthly_active_users': monthly_active_users,
        'total_sessions': total_sessions,
        'total_messages': total_messages,
        'total_requests': usage_totals['total_requests'] or 0,
        'total_cost': float(usage_totals['total_cost'] or 0),
        'total_tokens': usage_totals['total_tokens'] or 0,
        'avg_response_time': round(usage_totals['avg_latency'], 2) if usage_totals['avg_latency'] else 0,
        'images_generated': images_generated,
        'vision_calls': vision_calls,
        'chat_requests': chat_requests,
        'by_provider': by_provider,
        'by_model': by_model,
        'by_model_json': json.dumps(by_model),
        'daily_signups': daily_signups,
        'daily_signups_json': json.dumps(daily_signups),
        'daily_requests_json': json.dumps(daily_requests),
        'daily_cost_json': json.dumps(daily_cost),
        'daily_tokens_json': json.dumps(daily_tokens),
        'login_activity_json': json.dumps(login_activity),
        'by_provider_json': json.dumps(by_provider),
        'chat_vs_image_json': json.dumps({'chat': chat_requests, 'image': images_generated, 'vision': vision_calls}),
        'recent_errors': recent_errors,
        'recent_audit': recent_audit,
        'model_count': len(MODEL_REGISTRY),
        'maintenance_mode': FeatureFlag.is_enabled('maintenance_mode', default=False),
        'peak_hours_json': json.dumps(peak_hours),
        'most_active_users': most_active_users,
        'feature_flags_glance': feature_flags_glance,
        'db_stats': db_stats,
        'active_nav': 'dashboard',
    }
    return render(request, 'admin_console/dashboard.html', context)


# ================= Quick search (Cmd-K command palette) =================

@superuser_required
def admin_quick_search(request):
    """Backs the topbar's Cmd/Ctrl-K command palette (admin_console/base.html) -
    the static list of console pages is filtered entirely client-side; this
    endpoint answers "which real records match this text" across the
    handful of models an operator actually needs to jump straight to -
    users, chats, audit log entries, broadcasts, feature flags - each
    capped small (this is "jump to the thing I'm already thinking of", not
    a replacement for any model's own dedicated, fully-filterable list
    page)."""
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'users': [], 'chats': [], 'audit_log': [], 'broadcasts': [], 'feature_flags': []})

    users = User.objects.filter(
        Q(username__icontains=query) | Q(email__icontains=query)
    ).order_by('-date_joined')[:5]

    chats = ChatSession.objects.filter(title__icontains=query).select_related('user').order_by('-created_at')[:5]

    audit_entries = AdminAuditLog.objects.filter(
        Q(detail__icontains=query) | Q(action__icontains=query)
    ).select_related('actor', 'target_user').order_by('-created_at')[:5]

    broadcasts = Broadcast.objects.filter(message__icontains=query).order_by('-created_at')[:5]

    flags = FeatureFlag.objects.filter(
        Q(key__icontains=query) | Q(description__icontains=query)
    ).order_by('key')[:5]

    return JsonResponse({
        'users': [
            {'id': u.id, 'username': u.username, 'email': u.email, 'url': f'/admin-console/users/{u.id}/'}
            for u in users
        ],
        'chats': [
            {'id': c.id, 'title': c.title, 'owner': c.user.username if c.user else '-', 'url': f'/admin-console/users/{c.user_id}/' if c.user_id else ''}
            for c in chats
        ],
        'audit_log': [
            {'id': a.id, 'action': a.action, 'detail': a.detail[:80], 'url': '/admin-console/audit-log/'}
            for a in audit_entries
        ],
        'broadcasts': [
            {'id': b.id, 'message': b.message[:80], 'url': '/admin-console/broadcasts/'}
            for b in broadcasts
        ],
        'feature_flags': [
            {'key': f.key, 'description': f.description, 'url': '/admin-console/feature-flags/'}
            for f in flags
        ],
    })


# ================= Live platform monitor =================

@superuser_required
def admin_live_platform(request):
    return render(request, 'admin_console/live_platform.html', {'active_nav': 'live'})


@superuser_required
def admin_live_platform_data(request):
    """Polled every few seconds by admin_console/live_platform.html - kept
    deliberately cheap (small aggregates over short, indexed time windows,
    no full-table scans) since this is meant to be hit repeatedly, unlike
    every other admin-console view which loads once per page visit.

    Some numbers here are honest proxies rather than a real job queue -
    this project has no Celery/background-worker infrastructure, so
    "active generations" means "UsageEvent rows written in the last 60s",
    not a true in-flight count. Documented here rather than presented as
    something it isn't."""
    now = timezone.now()
    one_minute_ago = now - timedelta(seconds=60)
    five_minutes_ago = now - timedelta(minutes=5)

    db_start = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    db_latency_ms = round((time.monotonic() - db_start) * 1000, 1)

    online_users = SecurityEvent.objects.filter(
        event_type="login", created_at__gte=five_minutes_ago
    ).values('user').distinct().count()

    recent_events = UsageEvent.objects.filter(created_at__gte=one_minute_ago)
    requests_last_minute = recent_events.count()
    avg_latency = recent_events.aggregate(avg=Avg('latency'))['avg']

    by_type = dict(
        recent_events.values('event_type').annotate(n=Count('id')).values_list('event_type', 'n')
    )

    recent_errors_5m = SecurityEvent.objects.filter(
        severity__in=['warning', 'critical'], created_at__gte=five_minutes_ago
    ).count()

    live_feed = list(
        SecurityEvent.objects.select_related('user').order_by('-created_at')[:8]
        .values('created_at', 'event_type', 'severity', user_label=db_models.F('user__username'))
    ) + list(
        AdminAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')[:8]
        .values('created_at', 'action', actor_label=db_models.F('actor__username'), target_label=db_models.F('target_user__username'))
    )
    live_feed.sort(key=lambda e: e['created_at'], reverse=True)
    feed_out = []
    for e in live_feed[:12]:
        if 'action' in e:
            feed_out.append({
                'at': e['created_at'].isoformat(),
                'kind': 'admin_action',
                'text': f"{e['actor_label'] or 'system'} → {e['action']}" + (f" ({e['target_label']})" if e['target_label'] else ''),
            })
        else:
            feed_out.append({
                'at': e['created_at'].isoformat(),
                'kind': 'security_event',
                'text': f"{e['event_type']} - {e['user_label'] or 'unknown user'}",
                'severity': e['severity'],
            })

    return JsonResponse({
        'online_users': online_users,
        'requests_last_minute': requests_last_minute,
        'avg_latency_ms': round(avg_latency * 1000, 0) if avg_latency else None,
        'db_latency_ms': db_latency_ms,
        'active_chat_60s': by_type.get('chat', 0),
        'active_image_60s': by_type.get('image', 0),
        'active_vision_60s': by_type.get('vision', 0),
        'recent_errors_5m': recent_errors_5m,
        'feed': feed_out,
        'server_time': now.isoformat(),
    })


@superuser_required
def admin_live_log_stream(request):
    """Backs the Live Monitor's "Live Log Stream" panel - see
    chat/log_buffer.py for what this is (in-memory ring buffer, not a
    durable record). `since` lets the poller ask for only what's new."""
    from chat.log_buffer import get_recent_logs
    since = request.GET.get('since')
    since_float = float(since) if since else None
    logs = get_recent_logs(limit=100, since=since_float)
    return JsonResponse({'logs': logs})


# ================= System health =================

@superuser_required
def admin_system_health(request):
    return render(request, 'admin_console/system_health.html', {'active_nav': 'health'})


@superuser_required
def admin_system_health_data(request):
    """Real, honestly-labeled status checks - no fake "all green" states.
    AI provider "status" is a configuration + recent-success/failure check
    (does this process have credentials, and did the last call succeed),
    not a live ping - actually pinging every provider on every poll of this
    endpoint would be slow and would itself count as real API usage."""
    import os as os_module
    import psutil
    from chat.models import ErrorLog

    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    db_start = time.monotonic()
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        db_ok = False
    db_latency_ms = round((time.monotonic() - db_start) * 1000, 1)

    hourly_events = UsageEvent.objects.filter(created_at__gte=hour_ago)
    total_hourly = hourly_events.count()
    error_events_hourly = ErrorLog.objects.filter(last_seen__gte=hour_ago).aggregate(
        total=Sum('count')
    )['total'] or 0
    avg_latency = hourly_events.aggregate(avg=Avg('latency'))['avg']

    # pollinations.ai is used keyless (no API_KEY env var exists for it) -
    # treating it the same as the others would falsely show "not
    # configured" for a provider that was never supposed to need a key.
    KEYLESS_PROVIDERS = {'pollinations'}
    providers = {}
    for provider_key in ('groq', 'mistral', 'pollinations', 'tavily'):
        last_success = UsageEvent.objects.filter(provider=provider_key).order_by('-created_at').first()
        last_error = ErrorLog.objects.filter(
            detail__icontains=f"provider={provider_key}"
        ).order_by('-last_seen').first()
        providers[provider_key] = {
            'configured': True if provider_key in KEYLESS_PROVIDERS else bool(os_module.environ.get(f"{provider_key.upper()}_API_KEY")),
            'last_success': last_success.created_at.isoformat() if last_success else None,
            'last_error': last_error.last_seen.isoformat() if last_error else None,
        }

    return JsonResponse({
        'db_ok': db_ok,
        'db_latency_ms': db_latency_ms,
        'disk': psutil.disk_usage('/').percent,
        'ram': psutil.virtual_memory().percent,
        'cpu': psutil.cpu_percent(interval=None),
        'requests_last_hour': total_hourly,
        'avg_response_time_ms': round(avg_latency * 1000, 0) if avg_latency else None,
        'error_count_last_hour': error_events_hourly,
        'error_rate_percent': round((error_events_hourly / total_hourly) * 100, 2) if total_hourly else 0.0,
        'providers': providers,
        'queue_status': 'no background job queue is configured - AI requests are handled synchronously within the request/response cycle',
        'server_time': now.isoformat(),
    })


# ================= User management =================

USERS_LIST_SORT_FIELDS = {
    'username': 'username', 'email': 'email',
    'date_joined': 'date_joined', 'last_login': 'last_login',
}


def _build_users_queryset(request):
    """Shared between admin_users_list (paginated HTML) and
    admin_users_export_csv (full CSV) so the two can never silently drift -
    exporting "the current filtered list" must mean the same list you're
    looking at, not a re-implementation of the same filters."""
    from allauth.account.models import EmailAddress

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    verified_filter = request.GET.get('verified', '')
    admin_filter = request.GET.get('admin', '')
    online_filter = request.GET.get('online', '')
    recent_filter = request.GET.get('recent', '')
    role_filter = request.GET.get('role', '')
    sort = request.GET.get('sort', '-date_joined')

    users = User.objects.select_related('profile')

    if status_filter == 'deleted':
        users = users.filter(profile__is_deleted=True)
    else:
        # Soft-deleted accounts are hidden from every other view of this
        # list (including "all") - reachable only via the explicit "deleted"
        # filter or a direct link from the audit log, same convention as
        # most SaaS admin consoles use for soft-deleted records. profile
        # is created lazily (get_or_create_for, on first real use) rather
        # than at signup, so a brand new user may not have a profile row
        # yet - profile__isnull=True must stay visible here, since "no
        # profile yet" can't mean "deleted".
        users = users.filter(Q(profile__isnull=True) | Q(profile__is_deleted=False))

    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))

    if status_filter == 'active':
        users = users.filter(is_active=True, profile__is_banned=False)
    elif status_filter == 'banned':
        users = users.filter(profile__is_banned=True)
    elif status_filter == 'suspended':
        users = users.filter(profile__suspended_until__gt=timezone.now())
    elif status_filter == 'staff':
        # OR profile__isnull=True, is_staff=True: profiles are created
        # lazily (see UserProfile.get_or_create_for's docstring), so a
        # freshly created staff/superuser account with no profile row yet
        # must still show up here rather than being invisible until their
        # first login/page-view creates one - mirrors user_role()'s own
        # is_staff/is_superuser fallback for the same reason.
        users = users.filter(
            Q(profile__role__in=[Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR]) |
            Q(profile__isnull=True, is_staff=True)
        )
    elif status_filter == 'inactive':
        users = users.filter(is_active=False, profile__is_banned=False)

    if verified_filter:
        verified_ids = EmailAddress.objects.filter(verified=True).values_list('user_id', flat=True)
        users = users.filter(id__in=verified_ids) if verified_filter == 'yes' else users.exclude(id__in=verified_ids)

    if admin_filter == 'yes':
        users = users.filter(
            Q(profile__role__in=[Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN]) |
            Q(profile__isnull=True, is_staff=True)
        )

    if online_filter == 'yes':
        online_cutoff = timezone.now() - timedelta(minutes=5)
        online_ids = SecurityEvent.objects.filter(
            event_type="login", created_at__gte=online_cutoff
        ).values_list('user_id', flat=True)
        users = users.filter(id__in=online_ids)

    if recent_filter == 'yes':
        # "Recently active" = any AI usage in the last 7 days - a broader,
        # activity-based signal than "online" (logged in within 5 minutes).
        recent_cutoff = timezone.now() - timedelta(days=7)
        recent_ids = UsageEvent.objects.filter(created_at__gte=recent_cutoff).values_list('user_id', flat=True)
        users = users.filter(id__in=recent_ids)

    if role_filter:
        users = users.filter(profile__role=role_filter)

    sort_field = sort.lstrip('-')
    if sort_field in USERS_LIST_SORT_FIELDS:
        users = users.order_by(sort, 'id')
    else:
        sort = '-date_joined'
        users = users.order_by('-date_joined', 'id')

    filters = {
        'query': query, 'status_filter': status_filter, 'verified_filter': verified_filter,
        'admin_filter': admin_filter, 'online_filter': online_filter, 'recent_filter': recent_filter,
        'role_filter': role_filter, 'sort': sort,
    }
    return users, filters


def _next_sort(current_sort, field, default_desc=False):
    """Django's {% querystring %} tag only takes plain values, not inline
    if/else expressions - so the "what should this column header link to
    next" toggle logic is computed here instead of in template conditionals."""
    if current_sort == field:
        return f'-{field}'
    if current_sort == f'-{field}':
        return field
    return f'-{field}' if default_desc else field


@superuser_required
def admin_users_list(request):
    users, filters = _build_users_queryset(request)
    paginator = Paginator(users, 20)
    page = paginator.get_page(request.GET.get('page', '1'))
    sort = filters['sort']

    return render(request, 'admin_console/users_list.html', {
        'page': page,
        **filters,
        'verified_toggle': None if filters['verified_filter'] == 'yes' else 'yes',
        'unverified_toggle': None if filters['verified_filter'] == 'no' else 'no',
        'admin_toggle': None if filters['admin_filter'] == 'yes' else 'yes',
        'online_toggle': None if filters['online_filter'] == 'yes' else 'yes',
        'recent_toggle': None if filters['recent_filter'] == 'yes' else 'yes',
        'sort_username_next': _next_sort(sort, 'username'),
        'sort_email_next': _next_sort(sort, 'email'),
        'sort_joined_next': _next_sort(sort, 'date_joined', default_desc=True),
        'sort_last_login_next': _next_sort(sort, 'last_login', default_desc=True),
        'role_choices': Role.choices,
        'total_users': User.objects.count(),
        'active_nav': 'users',
    })


@superuser_required
def admin_users_export_csv(request):
    """Exports exactly the list currently filtered/sorted on the Users page
    (same queryset builder - see _build_users_queryset) as CSV, capped at
    5,000 rows so a pathologically broad filter can't turn this into an
    unbounded full-table streaming response."""
    from allauth.account.models import EmailAddress

    users, _filters = _build_users_queryset(request)
    rows = list(users.select_related('profile')[:5000])
    verified_ids = set(
        EmailAddress.objects.filter(user_id__in=[u.id for u in rows], verified=True).values_list('user_id', flat=True)
    )

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="simba_intel_users.csv"'
    writer = csv.writer(response)
    writer.writerow(['id', 'username', 'email', 'role', 'status', 'verified', 'date_joined', 'last_login'])
    for u in rows:
        profile = getattr(u, 'profile', None)
        role = profile.role if profile else 'user'
        if profile:
            status = 'deleted' if profile.is_deleted else 'banned' if profile.is_banned else \
                'suspended' if profile.is_suspended else 'blocked' if not u.is_active else 'active'
        else:
            status = 'active' if u.is_active else 'blocked'
        writer.writerow(_csv_safe_row([
            u.id, u.username, u.email, role, status,
            'yes' if u.id in verified_ids else 'no',
            u.date_joined.isoformat(), u.last_login.isoformat() if u.last_login else '',
        ]))
    _log(request, 'export_users_csv', None, f"{len(rows)} user(s), filters={dict(request.GET)}")
    return response


def _build_user_timeline(target, google_account, recovery_code, security_events, audit_history):
    """Merges every signal this app has about one account into a single,
    chronologically-sorted list - signup, Google linking, recovery code
    generation, security events (login/password change/etc, already
    fetched by the caller), admin actions taken on this account (role
    changes/bans/warnings/etc, also already fetched), and recent AI usage.
    Deliberately NOT every chat session ever created (that would be
    hundreds of near-identical entries for an active user) - usage is
    represented as a capped, most-recent slice, same convention as every
    other "recent activity" list in this console."""
    entries = [{'at': target.date_joined, 'kind': 'account', 'text': 'Account created'}]
    if google_account is not None:
        entries.append({'at': google_account.date_joined, 'kind': 'account', 'text': 'Connected Google account'})
    if recovery_code is not None:
        entries.append({'at': recovery_code.created_at, 'kind': 'account', 'text': 'Recovery code generated (current)'})

    for ev in security_events:
        entries.append({'at': ev.created_at, 'kind': 'security', 'text': f"{ev.event_type}: {ev.detail}" if ev.detail else ev.event_type})

    for log in audit_history:
        entries.append({'at': log.created_at, 'kind': 'admin', 'text': f"{log.action}" + (f" - {log.detail[:80]}" if log.detail else '')})

    recent_usage = UsageEvent.objects.filter(user=target).order_by('-created_at')[:15]
    for ev in recent_usage:
        entries.append({'at': ev.created_at, 'kind': 'usage', 'text': f"{ev.event_type} request ({ev.model_id})"})

    entries.sort(key=lambda e: e['at'], reverse=True)
    return entries[:60]


@superuser_required
def admin_user_detail(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile = UserProfile.get_or_create_for(target)

    if request.method == "POST":
        action = request.POST.get('action')

        # Owner protection: nobody may mutate the Owner's account except the
        # Owner themselves, and even the Owner can only touch their own role
        # via the dedicated transfer_ownership action below, never this
        # generic dispatcher - "Owner can never be deleted accidentally" and
        # "can never lose ownership unless ownership is explicitly
        # transferred" both live here, in one place, rather than repeated
        # per-action.
        if action != 'transfer_ownership' and not can_act_on_target(request.user, target):
            _log(request, 'blocked_attempt', target, f"attempted '{action}' on Owner account", success=False)
            return HttpResponseForbidden("The Owner account cannot be modified this way.")

        if action == 'block':
            target.is_active = False
            target.save(update_fields=['is_active'])
            _force_logout_user(target)
            _log(request, 'block', target)
        elif action == 'unblock':
            target.is_active = True
            target.save(update_fields=['is_active'])
            _log(request, 'unblock', target)
        elif action == 'suspend':
            days = int(request.POST.get('suspend_days', '1') or 1)
            reason = request.POST.get('reason', '').strip()
            profile.suspended_until = timezone.now() + timedelta(days=days)
            profile.suspend_reason = reason
            profile.save(update_fields=['suspended_until', 'suspend_reason'])
            _force_logout_user(target)
            _log(request, 'suspend', target, f"{days}d - {reason}")
        elif action == 'unsuspend':
            profile.suspended_until = None
            profile.suspend_reason = ''
            profile.save(update_fields=['suspended_until', 'suspend_reason'])
            _log(request, 'unsuspend', target)
        elif action == 'ban':
            reason = request.POST.get('reason', '').strip()
            profile.is_banned = True
            profile.ban_reason = reason
            profile.banned_at = timezone.now()
            profile.save(update_fields=['is_banned', 'ban_reason', 'banned_at'])
            target.is_active = False
            target.save(update_fields=['is_active'])
            _force_logout_user(target)
            _log(request, 'ban', target, reason)
        elif action == 'unban':
            profile.is_banned = False
            profile.ban_reason = ''
            profile.banned_at = None
            profile.save(update_fields=['is_banned', 'ban_reason', 'banned_at'])
            target.is_active = True
            target.save(update_fields=['is_active'])
            _log(request, 'unban', target)
        elif action == 'force_logout':
            killed = _force_logout_user(target)
            _log(request, 'force_logout', target, f"{killed} session(s) killed")
        elif action == 'delete_chats':
            count = ChatSession.objects.filter(user=target).count()
            ChatSession.objects.filter(user=target).delete()
            _log(request, 'delete_chats', target, f"{count} session(s) deleted")
        elif action == 'delete_uploads':
            # Uploaded files are already ephemeral (deleted right after
            # analysis, see chat/views.py's upload flow) - nothing persists
            # to delete here today. Logged anyway for a complete audit trail.
            _log(request, 'delete_uploads', target, "no persisted uploads to delete (ephemeral by design)")
        elif action == 'reset_password':
            from chat.models import RecoveryCode
            if target.has_usable_password():
                _recovery_code, raw_code = RecoveryCode.generate_for(target)
                # Shown once, here, in a flash message - there is no email
                # step to fall back on (see chat/models.py's RecoveryCode
                # docstring), so the admin is responsible for relaying this
                # to the account holder out-of-band right now.
                messages.success(
                    request,
                    f"New recovery code for {target.username} (copy this now, it will not be shown again): {raw_code}",
                )
                _log(request, 'reset_password', target, "New recovery code generated", success=True)
            else:
                messages.error(request, f"{target.username} signs in with Google and has no recovery code to reset.")
                _log(request, 'reset_password', target, "Skipped - Google-linked account has no recovery code", success=False)
        elif action == 'verify_email':
            from allauth.account.models import EmailAddress
            email_address, _created = EmailAddress.objects.get_or_create(
                user=target, email=target.email, defaults={'primary': True},
            )
            email_address.verified = True
            email_address.save(update_fields=['verified'])
            _log(request, 'verify_email', target)
        elif action == 'change_role':
            # Owner-tier role management only (matches the spec: Admin's own
            # capability list has no "manage roles" entry, and promoting/
            # demoting admins is called out as an Owner permission
            # specifically). Role.OWNER itself is never a valid target here
            # at all - not even the Owner may reach OWNER status through
            # this generic dropdown, only through transfer_ownership, which
            # is the one place "ownership changes are always explicit" is
            # actually enforced.
            if not has_role_at_least(request.user, Role.SUPER_ADMIN):
                return HttpResponseForbidden("Only Owner/Super Admin can change roles.")
            if profile.role == Role.OWNER:
                # Blocks this even when the actor IS the Owner acting on
                # themselves - the top-level guard above allows that case
                # through (self-action is normally fine), so this is the
                # actual enforcement point for "only via transfer_ownership".
                return HttpResponseForbidden("Ownership can only change via Transfer Ownership.")
            new_role = request.POST.get('role')
            valid_roles = {Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR, Role.VERIFIED, Role.USER}
            if new_role not in valid_roles:
                return HttpResponseForbidden("Invalid or disallowed role.")
            old_role = profile.role
            profile.role = new_role
            profile.save(update_fields=['role'])
            sync_django_flags(target, new_role)
            _log(request, 'change_role', target, f"{old_role} -> {new_role}")
        elif action == 'transfer_ownership':
            if not is_owner(request.user):
                return HttpResponseForbidden("Only the current Owner can transfer ownership.")
            if target.id == request.user.id:
                return HttpResponseForbidden("Cannot transfer ownership to yourself.")
            with transaction.atomic():
                actor_profile = UserProfile.get_or_create_for(request.user)
                actor_profile.role = Role.SUPER_ADMIN
                actor_profile.save(update_fields=['role'])
                sync_django_flags(request.user, Role.SUPER_ADMIN)

                profile.role = Role.OWNER
                profile.save(update_fields=['role'])
                sync_django_flags(target, Role.OWNER)
            _log(request, 'ownership_transfer', target, f"from {request.user.username} to {target.username}")
        elif action == 'add_note':
            note_text = request.POST.get('note', '').strip()
            if note_text:
                UserNote.objects.create(user=target, author=request.user, note=note_text)
                _log(request, 'add_note', target, note_text[:100])
        elif action == 'warn_user':
            # A step below suspend/ban - shows up on the user's own Timeline
            # and in the audit log, but doesn't itself change is_active or
            # any profile flag. Intentionally lightweight: there's no "3
            # warnings = auto-suspend" escalation logic here, just a record.
            warning_text = request.POST.get('warning', '').strip()
            if warning_text:
                _log(request, 'warn_user', target, warning_text[:200])
        elif action == 'delete_account':
            # Soft delete: the row itself, chat history, and usage/audit
            # records all stay - only login access is revoked and the
            # account drops out of the default user list. "Restore User"
            # reverses this exactly.
            profile.is_deleted = True
            profile.deleted_at = timezone.now()
            profile.save(update_fields=['is_deleted', 'deleted_at'])
            target.is_active = False
            target.save(update_fields=['is_active'])
            _force_logout_user(target)
            _log(request, 'delete_account', target)
        elif action == 'restore_account':
            profile.is_deleted = False
            profile.deleted_at = None
            profile.save(update_fields=['is_deleted', 'deleted_at'])
            # Only restore login access if nothing else is independently
            # blocking it - a banned account being un-deleted should stay
            # banned, not silently reactivated.
            if not profile.is_banned:
                target.is_active = True
                target.save(update_fields=['is_active'])
            _log(request, 'restore_account', target)
        elif action == 'update_usage_limits':
            profile.unlimited_usage = request.POST.get('unlimited_usage') == 'on'
            for field in ('daily_chat_limit', 'daily_image_limit', 'daily_vision_limit', 'daily_token_limit'):
                value = request.POST.get(field, '').strip()
                if value.isdigit():
                    setattr(profile, field, int(value))
            profile.save(update_fields=[
                'unlimited_usage', 'daily_chat_limit', 'daily_image_limit',
                'daily_vision_limit', 'daily_token_limit',
            ])
            detail = "unlimited" if profile.unlimited_usage else (
                f"chat={profile.daily_chat_limit} image={profile.daily_image_limit} "
                f"vision={profile.daily_vision_limit} tokens={profile.daily_token_limit}"
            )
            _log(request, 'update_usage_limits', target, detail)

        return redirect('admin_user_detail', user_id=target.id)

    sessions = ChatSession.objects.filter(user=target).order_by('-id')[:20]
    usage = UsageEvent.objects.filter(user=target).aggregate(
        total_requests=Count('id'),
        total_cost=Sum('estimated_cost_usd'),
        total_tokens=Sum(db_models.F('prompt_tokens') + db_models.F('completion_tokens')),
        total_images=Count('id', filter=Q(event_type='image')),
        total_vision=Count('id', filter=Q(event_type='vision')),
        total_chats=Count('id', filter=Q(event_type='chat')),
    )
    notes = UserNote.objects.filter(user=target).select_related('author')
    security_events = SecurityEvent.objects.filter(user=target).order_by('-created_at')[:20]
    audit_history = AdminAuditLog.objects.filter(target_user=target).select_related('actor').order_by('-created_at')[:20]

    # Active devices/sessions - cross-referenced against Django's live
    # Session table the same way the dashboard's active_sessions count is,
    # so a UserSession row for an already-expired session doesn't show as
    # "active" here either.
    live_session_keys = Session.objects.filter(expire_date__gte=timezone.now()).values_list('session_key', flat=True)
    active_devices = UserSession.objects.filter(user=target, session_key__in=live_session_keys).order_by('-created_at')

    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount
    from chat.models import RecoveryCode
    email_verified = EmailAddress.objects.filter(user=target, verified=True).exists()
    google_account = SocialAccount.objects.filter(user=target, provider='google').first()
    google_linked = google_account is not None
    recovery_code = RecoveryCode.objects.filter(user=target).first()

    timeline = _build_user_timeline(target, google_account, recovery_code, security_events, audit_history)

    return render(request, 'admin_console/user_detail.html', {
        'target': target,
        'profile': profile,
        'sessions': sessions,
        'total_sessions': ChatSession.objects.filter(user=target).count(),
        'usage': usage,
        'active_devices': active_devices,
        'email_verified': email_verified,
        'google_linked': google_linked,
        'recovery_code': recovery_code,
        'notes': notes,
        'security_events': security_events,
        'audit_history': audit_history,
        'timeline': timeline,
        'active_nav': 'users',
        'role_choices': [c for c in Role.choices if c[0] != Role.OWNER],
        'viewer_can_manage_roles': has_role_at_least(request.user, Role.SUPER_ADMIN),
        'viewer_is_owner': is_owner(request.user),
    })


@superuser_required
def admin_export_user_data(request, user_id):
    """A full, self-contained JSON export of everything this account owns -
    account/profile fields, usage totals, and every chat session with its
    full message tree (not just titles) - a genuine data export, not a
    summary, since that's what "Export User Data" means for an account
    owner asking what's held about them."""
    target = get_object_or_404(User, id=user_id)
    profile = UserProfile.get_or_create_for(target)

    # Prefetch with an explicit queryset (rather than a bare 'thread' prefetch
    # followed by .order_by() on it below) - calling .order_by() on an
    # already-prefetched related manager throws away the prefetch cache and
    # re-queries per session instead, turning this into an N+1.
    sessions_data = []
    for session in ChatSession.objects.filter(user=target).prefetch_related(
        Prefetch('thread', queryset=Message.objects.order_by('created_at'))
    ):
        sessions_data.append({
            'id': session.id,
            'title': session.title,
            'created_at': session.created_at.isoformat(),
            'messages': [
                {
                    'role': m.role,
                    'content': m.content,
                    'created_at': m.created_at.isoformat(),
                }
                for m in session.thread.all()
            ],
        })

    usage = UsageEvent.objects.filter(user=target).aggregate(
        total_requests=Count('id'), total_cost=Sum('estimated_cost_usd'),
        total_tokens=Sum(db_models.F('prompt_tokens') + db_models.F('completion_tokens')),
    )

    export = {
        'account': {
            'username': target.username,
            'email': target.email,
            'date_joined': target.date_joined.isoformat(),
            'is_active': target.is_active,
        },
        'profile': {
            'display_name': profile.display_name,
            'theme': profile.theme,
            'registration_source': profile.registration_source,
            'email_verified_at': profile.email_verified_at.isoformat() if profile.email_verified_at else None,
        },
        'usage_summary': {
            'total_requests': usage['total_requests'] or 0,
            'total_cost_usd': float(usage['total_cost'] or 0),
            'total_tokens': usage['total_tokens'] or 0,
        },
        'chat_sessions': sessions_data,
    }

    _log(request, 'export_user_data', target)
    response = JsonResponse(export, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="user_{target.id}_export.json"'
    return response


# ================= Audit log =================

def _build_audit_log_queryset(request):
    """Shared between admin_audit_log (paginated HTML) and
    admin_audit_log_export_csv, same reasoning as _build_users_queryset."""
    query = request.GET.get('q', '').strip()
    action_filter = request.GET.get('action', '')

    logs = AdminAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')

    if query:
        logs = logs.filter(
            Q(actor__username__icontains=query) | Q(actor__email__icontains=query) |
            Q(target_user__username__icontains=query) | Q(target_user__email__icontains=query) |
            Q(detail__icontains=query)
        )
    if action_filter:
        logs = logs.filter(action=action_filter)

    return logs, {'query': query, 'action_filter': action_filter}


@superuser_required
def admin_audit_log(request):
    logs, filters = _build_audit_log_queryset(request)
    paginator = Paginator(logs, 40)
    page = paginator.get_page(request.GET.get('page', '1'))
    return render(request, 'admin_console/audit_log.html', {
        'page': page,
        **filters,
        'action_choices': AdminAuditLog.ACTION_CHOICES,
        'active_nav': 'audit',
    })


@superuser_required
def admin_audit_log_export_csv(request):
    """Exports exactly the list currently filtered on the Audit Log page,
    capped at 10,000 rows for the same reason admin_users_export_csv is."""
    logs, _filters = _build_audit_log_queryset(request)
    rows = list(logs[:10000])

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="simba_intel_audit_log.csv"'
    writer = csv.writer(response)
    writer.writerow(['when', 'actor', 'action', 'target', 'detail', 'ip_address', 'browser', 'success'])
    for log in rows:
        writer.writerow(_csv_safe_row([
            log.created_at.isoformat(),
            log.actor.username if log.actor else '',
            log.action,
            log.target_user.username if log.target_user else '',
            log.detail, log.ip_address or '', log.browser, 'yes' if log.success else 'no',
        ]))
    _log(request, 'export_audit_log_csv', None, f"{len(rows)} row(s), filters={dict(request.GET)}")
    return response


# ================= Security panel =================

@superuser_required
def admin_security(request):
    failed_logins = FailedLoginAttempt.objects.order_by('-created_at')[:50]
    security_events = SecurityEvent.objects.select_related('user').order_by('-created_at')[:50]

    cutoff = timezone.now() - timedelta(hours=24)
    failed_last_24h = FailedLoginAttempt.objects.filter(created_at__gte=cutoff).count()
    top_targeted_emails = list(
        FailedLoginAttempt.objects.filter(created_at__gte=cutoff)
        .values('email_attempted').annotate(attempts=Count('id')).order_by('-attempts')[:10]
    )

    locked_accounts = User.objects.select_related('profile').filter(
        Q(profile__is_banned=True) | Q(profile__suspended_until__gt=timezone.now())
    ).order_by('-profile__banned_at')[:50]

    # "New device" isn't tracked as its own signal today (that would need
    # remembering every device a user has EVER used and diffing against it) -
    # the honest, available proxy is: a login from a user who has more than
    # one distinct (browser, device) pair in their recent history, meaning
    # something changed recently rather than every login looking identical.
    # exclude(user__isnull=True): SecurityEvent.user is nullable (SET_NULL) -
    # a hard-deleted account's old login events survive with user=None, and
    # grouping by user_id would otherwise lump every one of those together
    # under the same "user" (None), flagging them as suspicious device
    # changes for an account that no longer exists - found by testing this
    # exact scenario, not theoretical: it also crashed the template below,
    # which links straight to that (nonexistent) user's detail page.
    recent_logins = SecurityEvent.objects.filter(
        event_type='login', created_at__gte=timezone.now() - timedelta(days=7)
    ).exclude(user__isnull=True).select_related('user').order_by('user_id', '-created_at')[:2000]
    seen_pairs = {}
    new_device_logins = []
    for event in recent_logins:
        pair = (event.browser, event.device)
        prior = seen_pairs.get(event.user_id)
        if prior is not None and pair not in prior:
            new_device_logins.append(event)
        seen_pairs.setdefault(event.user_id, set()).add(pair)
    new_device_logins = new_device_logins[:20]

    login_days, logins_by_day = _daily_login_counts(14)
    login_timeline = [
        {'date': day.isoformat(), 'count': logins_by_day.get(day, 0)}
        for day in login_days
    ]

    # IP/browser/device breakdowns - real, honest signals (no geo-IP lookup
    # is wired into this project, so a "login map" isn't buildable without
    # adding a new geo database dependency; these grouped counts are the
    # available substitute). Single grouped query each, last 30 days.
    breakdown_cutoff = timezone.now() - timedelta(days=30)
    recent_security = SecurityEvent.objects.filter(event_type='login', created_at__gte=breakdown_cutoff)
    top_ips = list(
        recent_security.exclude(ip_address__isnull=True)
        .values('ip_address').annotate(count=Count('id')).order_by('-count')[:15]
    )
    top_browsers = list(
        recent_security.values('browser').annotate(count=Count('id')).order_by('-count')[:10]
    )
    top_devices = list(
        recent_security.values('device').annotate(count=Count('id')).order_by('-count')[:10]
    )

    return render(request, 'admin_console/security.html', {
        'failed_logins': failed_logins,
        'security_events': security_events,
        'failed_last_24h': failed_last_24h,
        'top_targeted_emails': top_targeted_emails,
        'locked_accounts': locked_accounts,
        'new_device_logins': new_device_logins,
        'login_timeline_json': json.dumps(login_timeline),
        'top_ips': top_ips,
        'top_browsers': top_browsers,
        'top_devices': top_devices,
        'active_nav': 'security',
    })


# ================= Feature flags =================

@superuser_required
def admin_feature_flags(request):
    if request.method == "POST":
        key = request.POST.get('key', '').strip()
        if request.POST.get('action') == 'create' and key:
            _flag, created = FeatureFlag.objects.get_or_create(key=key, defaults={
                'description': request.POST.get('description', '').strip(),
                'enabled': False,
            })
            if created:
                _log(request, 'feature_flag_create', None, f"'{key}'")
        elif request.POST.get('action') == 'toggle' and key:
            flag = FeatureFlag.objects.filter(key=key).first()
            if flag:
                flag.enabled = not flag.enabled
                flag.save(update_fields=['enabled'])
                _log(request, 'feature_flag_toggle', None, f"'{key}' -> {flag.enabled}")
        return redirect('admin_feature_flags')

    flags = FeatureFlag.objects.order_by('key')
    return render(request, 'admin_console/feature_flags.html', {'flags': flags, 'active_nav': 'flags'})


# ================= Report generator =================

REPORT_PERIOD_DAYS = {'daily': 1, 'weekly': 7, 'monthly': 30}


@superuser_required
def admin_reports(request):
    return render(request, 'admin_console/reports.html', {'active_nav': 'reports'})


@superuser_required
def admin_report_download(request, report_type):
    """One dispatcher for every "downloadable report" (Users and Audit Log
    already had their own dedicated CSV export views before this page
    existed - those keep working at their original URLs, and are just
    linked from here too, so this doesn't duplicate that logic)."""
    from chat.models import ErrorLog

    period = request.GET.get('period', 'weekly')
    days = REPORT_PERIOD_DAYS.get(period, 7)
    cutoff = timezone.now() - timedelta(days=days)

    response = HttpResponse(content_type='text/csv')
    writer = csv.writer(response)

    if report_type == 'usage':
        response['Content-Disposition'] = f'attachment; filename="simba_intel_usage_{period}.csv"'
        writer.writerow(['date', 'provider', 'model_id', 'event_type', 'requests', 'total_tokens', 'total_cost_usd'])
        rows = (
            UsageEvent.objects.filter(created_at__gte=cutoff)
            .annotate(day=TruncDate('created_at'))
            .values('day', 'provider', 'model_id', 'event_type')
            .annotate(
                requests=Count('id'),
                tokens=Sum(db_models.F('prompt_tokens') + db_models.F('completion_tokens')),
                cost=Sum('estimated_cost_usd'),
            ).order_by('day')
        )
        for row in rows:
            writer.writerow(_csv_safe_row([row['day'], row['provider'], row['model_id'], row['event_type'], row['requests'], row['tokens'] or 0, float(row['cost'] or 0)]))

    elif report_type == 'images':
        response['Content-Disposition'] = f'attachment; filename="simba_intel_images_{period}.csv"'
        writer.writerow(['when', 'user', 'model_id', 'latency_seconds', 'estimated_cost_usd'])
        rows = UsageEvent.objects.filter(
            event_type='image', created_at__gte=cutoff
        ).select_related('user').order_by('-created_at')[:5000]
        for row in rows:
            writer.writerow(_csv_safe_row([row.created_at.isoformat(), row.user.username if row.user else '', row.model_id, row.latency or '', float(row.estimated_cost_usd or 0)]))

    elif report_type == 'security':
        response['Content-Disposition'] = f'attachment; filename="simba_intel_security_{period}.csv"'
        writer.writerow(['when', 'user', 'event_type', 'severity', 'ip_address', 'detail'])
        rows = SecurityEvent.objects.filter(created_at__gte=cutoff).select_related('user').order_by('-created_at')[:5000]
        for row in rows:
            writer.writerow(_csv_safe_row([row.created_at.isoformat(), row.user.username if row.user else '', row.event_type, row.severity, row.ip_address or '', row.detail]))

    elif report_type == 'errors':
        response['Content-Disposition'] = f'attachment; filename="simba_intel_errors_{period}.csv"'
        writer.writerow(['category', 'message', 'count', 'first_seen', 'last_seen', 'resolved'])
        rows = ErrorLog.objects.filter(last_seen__gte=cutoff).order_by('-last_seen')[:5000]
        for row in rows:
            writer.writerow(_csv_safe_row([row.category, row.message, row.count, row.first_seen.isoformat(), row.last_seen.isoformat(), 'yes' if row.resolved else 'no']))

    else:
        return HttpResponseForbidden("Unknown report type.")

    _log(request, 'report_generated', None, f"{report_type} ({period})")
    return response


# ================= Role management =================

@superuser_required
def admin_roles(request):
    """Read-only visualization of chat/permissions.py's role hierarchy and
    PERMISSIONS capability matrix - actual role changes still happen from
    a user's own detail page (admin_user_detail's change_role action),
    which is the one place that mutation is already correctly gated and
    audit-logged; duplicating that logic here would just be a second place
    for the same rule to drift out of sync."""
    from chat.permissions import PERMISSIONS, ROLE_LEVEL

    role_counts = dict(
        UserProfile.objects.values('role').annotate(count=Count('id')).values_list('role', 'count')
    )
    roles = [
        {
            'value': role, 'label': label, 'level': ROLE_LEVEL.get(role, 0),
            'count': role_counts.get(role, 0),
        }
        for role, label in Role.choices
    ]
    permission_matrix = [
        {'action': action, 'roles': sorted(allowed_roles, key=lambda r: -ROLE_LEVEL.get(r, 0))}
        for action, allowed_roles in PERMISSIONS.items()
    ]
    return render(request, 'admin_console/roles.html', {
        'roles': roles,
        'permission_matrix': permission_matrix,
        'all_roles': [r for r, _ in Role.choices],
        'active_nav': 'roles',
    })


# ================= Settings hub =================

@superuser_required
def admin_settings(request):
    """A categorized index, not a mega-form: most of what's "settings" in
    this app already has its own dedicated, properly-scoped management page
    (Feature Flags, AI Control, Security, Broadcasts, Roles) - duplicating
    those forms here would just create a second place for the same value to
    drift out of sync. This page's job is helping an operator find the
    right one quickly, organized the way the spec asked for, plus a handful
    of genuinely read-only System values that don't have a home anywhere
    else."""
    from django.conf import settings as django_settings

    categories = [
        {
            'name': 'Authentication', 'icon': 'fa-key',
            'links': [
                ('Feature Flags (registration, Google login)', 'admin_feature_flags'),
                ('Roles & Permissions', 'admin_roles'),
            ],
        },
        {
            'name': 'Security', 'icon': 'fa-lock',
            'links': [('Security Center', 'admin_security'), ('Audit Log', 'admin_audit_log')],
        },
        {
            'name': 'AI', 'icon': 'fa-brain',
            'links': [('AI Control Center', 'admin_ai_control')],
        },
        {
            'name': 'Models', 'icon': 'fa-microchip',
            'links': [('Model Access (AI Control Center)', 'admin_ai_control')],
        },
        {
            'name': 'Analytics', 'icon': 'fa-chart-line',
            'links': [('Dashboard', 'admin_dashboard'), ('Reports', 'admin_reports')],
        },
        {
            'name': 'Platform', 'icon': 'fa-bullhorn',
            'links': [('Broadcasts & Announcements', 'admin_broadcasts'), ('Feature Flags', 'admin_feature_flags')],
        },
        {
            'name': 'System', 'icon': 'fa-server',
            'links': [('System Health', 'admin_system_health'), ('Live Monitor', 'admin_live_platform'), ('Error Center', 'admin_errors')],
        },
    ]

    system_info = {
        'debug': django_settings.DEBUG,
        'database_engine': django_settings.DATABASES['default']['ENGINE'].rsplit('.', 1)[-1],
        'email_backend': django_settings.EMAIL_BACKEND.rsplit('.', 1)[-1],
        'site_id': getattr(django_settings, 'SITE_ID', None),
        'allowed_hosts': ', '.join(django_settings.ALLOWED_HOSTS),
    }

    return render(request, 'admin_console/settings.html', {
        'categories': categories,
        'system_info': system_info,
        'active_nav': 'settings',
    })


# ================= AI Control Center =================

# The "curated" AI feature flags this page centers around - a deliberate
# subset of everything in FeatureFlag (which also holds registration/
# google_login/email_verification/maintenance_mode, all managed from their
# own pages already). Each maps to a real, enforced check in chat/views.py's
# ask_ai/upload_file - toggling one here genuinely changes product behavior,
# immediately, no redeploy.
AI_CONTROL_FLAGS = [
    ('ai_chat', 'Chat', 'Text conversation with the AI models.'),
    ('image_generation', 'Image Generation', 'Image Studio (Pollinations) image generation.'),
    ('vision', 'Vision', 'Image analysis via vision-capable models.'),
    ('file_upload', 'File Upload', 'Attaching files/images to a chat message.'),
    ('web_search', 'Web Search', 'Automatic Tavily web search augmentation for search-like queries.'),
]


@superuser_required
def admin_ai_control(request):
    if request.method == "POST":
        key = request.POST.get('key', '')
        valid_keys = {k for k, _, _ in AI_CONTROL_FLAGS}
        if key in valid_keys:
            flag, _created = FeatureFlag.objects.get_or_create(key=key, defaults={'enabled': True})
            flag.enabled = not flag.enabled
            flag.save(update_fields=['enabled'])
            _log(request, 'feature_flag_toggle', None, f"'{key}' -> {flag.enabled}")
        return redirect('admin_ai_control')

    flags_by_key = {f.key: f for f in FeatureFlag.objects.filter(key__in=[k for k, _, _ in AI_CONTROL_FLAGS])}
    flags = [
        {
            'key': key, 'label': label, 'description': description,
            'enabled': flags_by_key[key].enabled if key in flags_by_key else True,
        }
        for key, label, description in AI_CONTROL_FLAGS
    ]
    return render(request, 'admin_console/ai_control.html', {
        'flags': flags,
        'models': list_available_models(),
        'active_nav': 'ai_control',
    })


# ================= Error Center =================

@superuser_required
def admin_errors(request):
    from chat.models import ErrorLog

    category_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', 'unresolved')

    errors = ErrorLog.objects.all()
    if category_filter:
        errors = errors.filter(category=category_filter)
    if status_filter == 'unresolved':
        errors = errors.filter(resolved=False)
    elif status_filter == 'resolved':
        errors = errors.filter(resolved=True)

    paginator = Paginator(errors, 30)
    page = paginator.get_page(request.GET.get('page', '1'))

    return render(request, 'admin_console/errors.html', {
        'page': page,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'category_choices': ErrorLog.CATEGORY_CHOICES,
        'unresolved_count': ErrorLog.objects.filter(resolved=False).count(),
        # Real, existing signals that already function as "Authentication
        # Errors" - not duplicated into ErrorLog since FailedLoginAttempt
        # already is that data, one source of truth.
        'recent_auth_errors': FailedLoginAttempt.objects.order_by('-created_at')[:10],
        'active_nav': 'errors',
    })


@superuser_required
def admin_error_resolve(request, error_id):
    from chat.models import ErrorLog
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)
    error = get_object_or_404(ErrorLog, id=error_id)
    error.resolved = True
    error.resolved_at = timezone.now()
    error.resolved_by = request.user
    error.save(update_fields=['resolved', 'resolved_at', 'resolved_by'])
    _log(request, 'error_resolved', None, f"{error.category}: {error.message[:80]}")
    return redirect('admin_errors')


# ================= Broadcasts =================

def _daily_login_counts(days):
    """(date_list, counts_dict) for the last `days` days of SecurityEvent
    login events - shared by the dashboard's Login Activity chart and the
    Security Center's login timeline so both compute it exactly once."""
    today = timezone.localdate()
    window_start = today - timedelta(days=days - 1)
    counts = dict(
        SecurityEvent.objects.filter(event_type='login', created_at__date__gte=window_start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .values_list('day', 'count')
    )
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)], counts


def _parse_local_datetime(value):
    """HTML <input type="datetime-local"> posts "YYYY-MM-DDTHH:MM" with no
    timezone - naive by construction, made aware in the server's own TIME_ZONE
    (there's no per-admin timezone preference stored anywhere to use instead)."""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


@superuser_required
def admin_broadcasts(request):
    if request.method == "POST":
        if request.POST.get('action') == 'create':
            message = request.POST.get('message', '').strip()
            if message:
                Broadcast.objects.filter(active=True).update(active=False)
                broadcast = Broadcast.objects.create(
                    message=message,
                    level=request.POST.get('level', 'info'),
                    created_by=request.user,
                    active=True,
                    is_popup=request.POST.get('is_popup') == 'on',
                    dismissible=request.POST.get('dismissible') == 'on',
                    starts_at=_parse_local_datetime(request.POST.get('starts_at', '')),
                    ends_at=_parse_local_datetime(request.POST.get('ends_at', '')),
                )
                _log(request, 'broadcast_create', None, f"[{broadcast.status}] {message[:100]}")
        elif request.POST.get('action') == 'deactivate':
            broadcast_id = request.POST.get('broadcast_id')
            Broadcast.objects.filter(id=broadcast_id).update(active=False)
            _log(request, 'broadcast_deactivate', None, f"broadcast #{broadcast_id}")
        return redirect('admin_broadcasts')

    broadcasts = Broadcast.objects.order_by('-created_at')[:20]
    return render(request, 'admin_console/broadcasts.html', {'broadcasts': broadcasts, 'active_nav': 'broadcasts'})
