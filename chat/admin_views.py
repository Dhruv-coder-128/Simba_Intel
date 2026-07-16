"""Custom Super Admin Console - deliberately NOT django.contrib.admin.
Every view here is role-gated via @require_role(Role.ADMIN) (chat/
permissions.py) and every mutating action is written to AdminAuditLog. Kept
in its own module rather than chat/views.py (already 1000+ lines covering
the actual product) so the two surfaces - user-facing app vs. operator
console - stay easy to tell apart.
"""
import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db import models as db_models, transaction
from django.db.models import Avg, Count, Sum, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from chat.models import (
    AdminAuditLog, Broadcast, ChatSession, FailedLoginAttempt,
    FeatureFlag, Message, Role, SecurityEvent, UsageEvent, UserNote, UserProfile, UserSession,
)
from chat.permissions import (
    can_act_on_target, has_role_at_least, is_owner, require_permission,
    require_role, sync_django_flags,
)
from chat.services.model_registry import MODEL_REGISTRY
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

    recent_errors = SecurityEvent.objects.filter(severity__in=['warning', 'critical']).order_by('-created_at')[:10]
    recent_audit = AdminAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')[:10]

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'banned_users': banned_users,
        'staff_users': staff_users,
        'verified_users': verified_users,
        'unverified_users': unverified_users,
        'online_users': online_users,
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
        'active_nav': 'dashboard',
    }
    return render(request, 'admin_console/dashboard.html', context)


# ================= User management =================

@superuser_required
def admin_users_list(request):
    from allauth.account.models import EmailAddress

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    verified_filter = request.GET.get('verified', '')
    admin_filter = request.GET.get('admin', '')
    online_filter = request.GET.get('online', '')
    recent_filter = request.GET.get('recent', '')
    page_number = request.GET.get('page', '1')

    users = User.objects.select_related('profile').order_by('-date_joined')

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

    paginator = Paginator(users, 20)
    page = paginator.get_page(page_number)

    return render(request, 'admin_console/users_list.html', {
        'page': page,
        'query': query,
        'status_filter': status_filter,
        'verified_filter': verified_filter,
        'admin_filter': admin_filter,
        'online_filter': online_filter,
        'recent_filter': recent_filter,
        'total_users': User.objects.count(),
        'active_nav': 'users',
    })


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
    email_verified = EmailAddress.objects.filter(user=target, verified=True).exists()
    google_linked = SocialAccount.objects.filter(user=target, provider='google').exists()

    return render(request, 'admin_console/user_detail.html', {
        'target': target,
        'profile': profile,
        'sessions': sessions,
        'total_sessions': ChatSession.objects.filter(user=target).count(),
        'usage': usage,
        'active_devices': active_devices,
        'email_verified': email_verified,
        'google_linked': google_linked,
        'notes': notes,
        'security_events': security_events,
        'audit_history': audit_history,
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

    sessions_data = []
    for session in ChatSession.objects.filter(user=target).prefetch_related('thread'):
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
                for m in session.thread.order_by('created_at')
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

@superuser_required
def admin_audit_log(request):
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

    paginator = Paginator(logs, 40)
    page = paginator.get_page(request.GET.get('page', '1'))
    return render(request, 'admin_console/audit_log.html', {
        'page': page,
        'query': query,
        'action_filter': action_filter,
        'action_choices': AdminAuditLog.ACTION_CHOICES,
        'active_nav': 'audit',
    })


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
    recent_logins = SecurityEvent.objects.filter(
        event_type='login', created_at__gte=timezone.now() - timedelta(days=7)
    ).select_related('user').order_by('user_id', '-created_at')[:2000]
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

    return render(request, 'admin_console/security.html', {
        'failed_logins': failed_logins,
        'security_events': security_events,
        'failed_last_24h': failed_last_24h,
        'top_targeted_emails': top_targeted_emails,
        'locked_accounts': locked_accounts,
        'new_device_logins': new_device_logins,
        'login_timeline_json': json.dumps(login_timeline),
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
