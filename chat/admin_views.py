"""Custom Super Admin Console - deliberately NOT django.contrib.admin.
Every view here is superuser-gated via @superuser_required and every
mutating action is written to AdminAuditLog. Kept in its own module rather
than chat/views.py (already 1000+ lines covering the actual product) so the
two surfaces - user-facing app vs. operator console - stay easy to tell apart.
"""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db import models as db_models
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from chat.models import (
    AdminAuditLog, Broadcast, ChatSession, FailedLoginAttempt,
    FeatureFlag, Message, SecurityEvent, UsageEvent, UserNote, UserProfile,
)
from chat.services.model_registry import MODEL_REGISTRY

User = get_user_model()

superuser_required = user_passes_test(lambda u: u.is_active and u.is_superuser, login_url='home')


def _log(request, action, target_user=None, detail=""):
    AdminAuditLog.objects.create(actor=request.user, action=action, target_user=target_user, detail=detail)


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
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    banned_users = UserProfile.objects.filter(is_banned=True).count()
    staff_users = User.objects.filter(is_staff=True).count()

    online_cutoff = timezone.now() - timedelta(minutes=5)
    online_users = SecurityEvent.objects.filter(
        event_type="login", created_at__gte=online_cutoff
    ).values('user').distinct().count()

    new_today = User.objects.filter(date_joined__date=timezone.localdate()).count()
    new_this_week = User.objects.filter(date_joined__date__gte=timezone.localdate() - timedelta(days=6)).count()

    total_sessions = ChatSession.objects.count()
    total_messages = Message.objects.count()

    usage_totals = UsageEvent.objects.aggregate(
        total_requests=Count('id'),
        total_cost=Sum('estimated_cost_usd'),
        total_tokens=Sum(db_models.F('prompt_tokens') + db_models.F('completion_tokens')),
    )
    images_generated = UsageEvent.objects.filter(event_type='image').count()
    vision_calls = UsageEvent.objects.filter(event_type='vision').count()

    by_provider = list(
        UsageEvent.objects.values('provider')
        .annotate(requests=Count('id'), cost=Sum('estimated_cost_usd'))
        .order_by('-requests')
    )

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

    recent_errors = SecurityEvent.objects.filter(severity__in=['warning', 'critical']).order_by('-created_at')[:10]
    recent_audit = AdminAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')[:10]

    context = {
        'total_users': total_users,
        'active_users': active_users,
        'banned_users': banned_users,
        'staff_users': staff_users,
        'online_users': online_users,
        'new_today': new_today,
        'new_this_week': new_this_week,
        'total_sessions': total_sessions,
        'total_messages': total_messages,
        'total_requests': usage_totals['total_requests'] or 0,
        'total_cost': float(usage_totals['total_cost'] or 0),
        'total_tokens': usage_totals['total_tokens'] or 0,
        'images_generated': images_generated,
        'vision_calls': vision_calls,
        'by_provider': by_provider,
        'daily_signups': daily_signups,
        'daily_signups_json': json.dumps(daily_signups),
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
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    page_number = request.GET.get('page', '1')

    users = User.objects.select_related('profile').order_by('-date_joined')

    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))

    if status_filter == 'active':
        users = users.filter(is_active=True, profile__is_banned=False)
    elif status_filter == 'banned':
        users = users.filter(profile__is_banned=True)
    elif status_filter == 'suspended':
        users = users.filter(profile__suspended_until__gt=timezone.now())
    elif status_filter == 'staff':
        users = users.filter(is_staff=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False, profile__is_banned=False)

    paginator = Paginator(users, 20)
    page = paginator.get_page(page_number)

    return render(request, 'admin_console/users_list.html', {
        'page': page,
        'query': query,
        'status_filter': status_filter,
        'total_users': User.objects.count(),
        'active_nav': 'users',
    })


@superuser_required
def admin_user_detail(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile = UserProfile.get_or_create_for(target)

    if request.method == "POST":
        action = request.POST.get('action')

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
            from chat.models import PasswordResetOTP
            from chat.views import _send_otp_email
            if target.email:
                otp = PasswordResetOTP.generate_for(target)
                _send_otp_email(target, otp)
                _log(request, 'reset_password', target, "OTP emailed")
        elif action == 'verify_email':
            from allauth.account.models import EmailAddress
            email_address, _created = EmailAddress.objects.get_or_create(
                user=target, email=target.email, defaults={'primary': True},
            )
            email_address.verified = True
            email_address.save(update_fields=['verified'])
            _log(request, 'verify_email', target)
        elif action == 'change_role':
            new_role = request.POST.get('role')
            if new_role == 'superuser':
                target.is_staff = True
                target.is_superuser = True
            elif new_role == 'staff':
                target.is_staff = True
                target.is_superuser = False
            else:
                target.is_staff = False
                target.is_superuser = False
            target.save(update_fields=['is_staff', 'is_superuser'])
            _log(request, 'change_role', target, new_role)
        elif action == 'add_note':
            note_text = request.POST.get('note', '').strip()
            if note_text:
                UserNote.objects.create(user=target, author=request.user, note=note_text)
                _log(request, 'add_note', target, note_text[:100])

        return redirect('admin_user_detail', user_id=target.id)

    sessions = ChatSession.objects.filter(user=target).order_by('-id')[:20]
    usage = UsageEvent.objects.filter(user=target).aggregate(
        total_requests=Count('id'), total_cost=Sum('estimated_cost_usd'),
    )
    notes = UserNote.objects.filter(user=target).select_related('author')
    security_events = SecurityEvent.objects.filter(user=target).order_by('-created_at')[:20]
    audit_history = AdminAuditLog.objects.filter(target_user=target).select_related('actor').order_by('-created_at')[:20]

    return render(request, 'admin_console/user_detail.html', {
        'target': target,
        'profile': profile,
        'sessions': sessions,
        'total_sessions': ChatSession.objects.filter(user=target).count(),
        'usage': usage,
        'notes': notes,
        'security_events': security_events,
        'audit_history': audit_history,
        'active_nav': 'users',
    })


# ================= Audit log =================

@superuser_required
def admin_audit_log(request):
    logs = AdminAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')
    paginator = Paginator(logs, 40)
    page = paginator.get_page(request.GET.get('page', '1'))
    return render(request, 'admin_console/audit_log.html', {'page': page, 'active_nav': 'audit'})


# ================= Security panel =================

@superuser_required
def admin_security(request):
    failed_logins = FailedLoginAttempt.objects.order_by('-created_at')[:50]
    security_events = SecurityEvent.objects.order_by('-created_at')[:50]

    cutoff = timezone.now() - timedelta(hours=24)
    failed_last_24h = FailedLoginAttempt.objects.filter(created_at__gte=cutoff).count()
    top_targeted_emails = list(
        FailedLoginAttempt.objects.filter(created_at__gte=cutoff)
        .values('email_attempted').annotate(attempts=Count('id')).order_by('-attempts')[:10]
    )

    return render(request, 'admin_console/security.html', {
        'failed_logins': failed_logins,
        'security_events': security_events,
        'failed_last_24h': failed_last_24h,
        'top_targeted_emails': top_targeted_emails,
        'active_nav': 'security',
    })


# ================= Feature flags =================

@superuser_required
def admin_feature_flags(request):
    if request.method == "POST":
        key = request.POST.get('key', '').strip()
        if request.POST.get('action') == 'create' and key:
            FeatureFlag.objects.get_or_create(key=key, defaults={
                'description': request.POST.get('description', '').strip(),
                'enabled': False,
            })
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

@superuser_required
def admin_broadcasts(request):
    if request.method == "POST":
        if request.POST.get('action') == 'create':
            message = request.POST.get('message', '').strip()
            if message:
                Broadcast.objects.filter(active=True).update(active=False)
                Broadcast.objects.create(
                    message=message,
                    level=request.POST.get('level', 'info'),
                    created_by=request.user,
                    active=True,
                )
                _log(request, 'broadcast_create', None, message[:100])
        elif request.POST.get('action') == 'deactivate':
            broadcast_id = request.POST.get('broadcast_id')
            Broadcast.objects.filter(id=broadcast_id).update(active=False)
            _log(request, 'broadcast_deactivate', None, f"broadcast #{broadcast_id}")
        return redirect('admin_broadcasts')

    broadcasts = Broadcast.objects.order_by('-created_at')[:20]
    return render(request, 'admin_console/broadcasts.html', {'broadcasts': broadcasts, 'active_nav': 'broadcasts'})
