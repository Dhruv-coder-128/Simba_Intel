import random
from datetime import timedelta

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions', null=True, blank=True)
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    is_pinned = models.BooleanField(default=False)
    # The current tip of the active branch in this session's message tree.
    # NULL means the session has no Message-tree history yet (e.g. legacy
    # sessions before this field existed, or a brand new session).
    active_leaf = models.ForeignKey(
        'Message', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )

    def __str__(self):
        return self.title

class ChatMessage(models.Model):
    """Legacy turn-paired message log. Frozen as of the Phase 3 schema migration -
    kept forever as a permanent audit/rollback copy. New writes go to Message."""
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    user_query = models.TextField()
    ai_response = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    latency = models.FloatField(null=True, blank=True)
    # New field for image/extra data (JSON)
    extra_data = models.JSONField(null=True, blank=True)


class Message(models.Model):
    """Role-based, branchable message tree. Replaces ChatMessage for all new
    writes as of Phase 3. Editing a user message or regenerating an assistant
    reply creates a new sibling under the same parent rather than mutating
    anything in place - old branches stay in the DB, just not on the active
    path (ChatSession.active_leaf)."""

    ROLE_CHOICES = [
        ('system', 'system'),
        ('user', 'user'),
        ('assistant', 'assistant'),
        ('tool', 'tool'),
    ]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='thread')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children'
    )
    extra_data = models.JSONField(null=True, blank=True)
    latency = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['parent']),
        ]

    def __str__(self):
        preview = (self.content or '')[:40]
        return f"{self.role}: {preview}"


class UserProfile(models.Model):
    THEME_CHOICES = [
        ("cyberpunk", "Cyber Dark (default)"),
        ("midnight-purple", "Midnight"),
        ("matrix-green", "Matrix"),
        ("nord", "Nord"),
        ("synthwave", "Synthwave"),
        ("purple-neon", "Purple Neon"),
        ("ocean", "Ocean"),
        ("minimal-dark", "Minimal Dark"),
        ("graphite", "Graphite"),
        ("light", "Light"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=100, blank=True)
    avatar_url = models.URLField(blank=True)
    default_model = models.CharField(max_length=50, default='cyber-max')
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='cyberpunk')
    memory_enabled = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Admin console moderation state ---
    # Ban/suspend are deliberately separate from User.is_active: is_active is
    # still flipped to False for both (that's what actually blocks Django/
    # allauth login), but keeping the reason/expiry here means the admin
    # console can show *why* someone is locked out and auto-distinguish a
    # temporary suspension from a permanent ban, instead of just "inactive".
    is_banned = models.BooleanField(default=False)
    ban_reason = models.TextField(blank=True)
    banned_at = models.DateTimeField(null=True, blank=True)
    suspended_until = models.DateTimeField(null=True, blank=True)
    suspend_reason = models.TextField(blank=True)

    def __str__(self):
        return f"Profile({self.user})"

    @classmethod
    def get_or_create_for(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile

    @property
    def is_suspended(self):
        return bool(self.suspended_until and self.suspended_until > timezone.now())


class UsageEvent(models.Model):
    """One record per AI call (chat turn, vision call, or image generation),
    used for cost estimation, analytics, and DB-backed rate limiting."""

    EVENT_TYPE_CHOICES = [
        ("chat", "chat"),
        ("vision", "vision"),
        ("image", "image"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usage_events')
    session = models.ForeignKey(
        ChatSession, null=True, blank=True, on_delete=models.SET_NULL, related_name='usage_events'
    )
    provider = models.CharField(max_length=30)
    model_id = models.CharField(max_length=50)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    # True when prompt/completion_tokens come from a len(text)/4 heuristic
    # rather than a real usage payload from the provider.
    tokens_are_estimated = models.BooleanField(default=True)
    latency = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            # Covers the admin dashboard's per-type breakdowns (images_generated,
            # vision_calls) which filter on event_type alone across the whole table.
            models.Index(fields=['event_type', 'created_at']),
        ]

    def __str__(self):
        return f"UsageEvent({self.user}, {self.model_id}, {self.event_type})"


class PasswordResetOTP(models.Model):
    """A single-use 6-digit code emailed to the user for the
    Forgot Password -> Email OTP -> Verify OTP -> New Password flow.
    Deliberately separate from django-allauth's own (link-based) reset flow -
    that flow is untouched and still works, this is an additional path."""

    OTP_VALID_MINUTES = 10
    OTP_RESEND_COOLDOWN_SECONDS = 30

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_otps')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=['user', 'created_at'])]

    def __str__(self):
        return f"PasswordResetOTP({self.user}, used={self.used})"

    def is_valid(self):
        if self.used:
            return False
        return timezone.now() - self.created_at < timedelta(minutes=self.OTP_VALID_MINUTES)

    @classmethod
    def generate_for(cls, user):
        # Invalidate any earlier still-usable codes so only the most recently
        # emailed one can ever succeed - otherwise an old, previously-seen
        # code would stay valid for its own full 10-minute window too.
        cls.objects.filter(user=user, used=False).update(used=True)
        code = f"{random.randint(0, 999999):06d}"
        return cls.objects.create(user=user, code=code)


# ================= Custom Super Admin Console =================
# Deliberately NOT django.contrib.admin - a separate, superuser-gated set of
# views (chat/admin_views.py) built for actually running this as a product:
# moderation actions, audit trail, feature flags, broadcasts. These models
# back that console; nothing here is read by the regular chat/analytics code.

class AdminAuditLog(models.Model):
    """Every action a superuser takes against a user account through the
    admin console, so "who banned this person and why" is always answerable."""

    ACTION_CHOICES = [
        ("block", "block"),
        ("unblock", "unblock"),
        ("suspend", "suspend"),
        ("unsuspend", "unsuspend"),
        ("ban", "ban"),
        ("unban", "unban"),
        ("force_logout", "force_logout"),
        ("delete_chats", "delete_chats"),
        ("delete_uploads", "delete_uploads"),
        ("reset_password", "reset_password"),
        ("verify_email", "verify_email"),
        ("change_role", "change_role"),
        ("add_note", "add_note"),
        ("feature_flag_toggle", "feature_flag_toggle"),
        ("broadcast_create", "broadcast_create"),
        ("broadcast_deactivate", "broadcast_deactivate"),
    ]

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='admin_actions_taken')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='admin_actions_received')
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['-created_at'])]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.actor} {self.action} {self.target_user}"


class UserNote(models.Model):
    """Free-text internal notes an admin leaves on a user's account -
    support context, moderation history, anything not worth its own field."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_notes')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.user} by {self.author}"


class FailedLoginAttempt(models.Model):
    """Populated by a signal receiver on django.contrib.auth.signals.user_login_failed
    (see chat/signals.py) - used for the admin security panel and basic
    brute-force visibility. Deliberately not tied to a User FK: a failed
    login for a nonexistent email is exactly the case worth recording."""

    email_attempted = models.CharField(max_length=254, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['email_attempted', '-created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Failed login: {self.email_attempted} @ {self.ip_address}"


class SecurityEvent(models.Model):
    """Generic security/moderation log - new-device logins, rate-limit hits,
    and heuristic content flags (the "AI moderation" signal) all land here
    rather than each getting a bespoke model, so the admin security panel has
    one place to read from."""

    SEVERITY_CHOICES = [
        ("info", "info"),
        ("warning", "warning"),
        ("critical", "critical"),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='security_events')
    event_type = models.CharField(max_length=50)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="info")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['severity', '-created_at']),
            # Covers the admin dashboard's "online users" query: filter on
            # event_type='login' + created_at__gte=cutoff.
            models.Index(fields=['event_type', '-created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.severity}] {self.event_type} ({self.user})"


class FeatureFlag(models.Model):
    """Simple on/off switches read at request time - no caching layer, this
    app's traffic doesn't need one yet and it'd be a real bug source if the
    flag changed and a stale cached value kept the old behavior live."""

    key = models.SlugField(max_length=50, unique=True)
    enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key} = {self.enabled}"

    @classmethod
    def is_enabled(cls, key, default=True):
        flag = cls.objects.filter(key=key).first()
        return flag.enabled if flag else default


class Broadcast(models.Model):
    """A single active banner shown to every logged-in user - maintenance
    notices, incident updates, announcements. Only one is meant to be
    .active at a time; the admin console enforces that on save."""

    LEVEL_CHOICES = [
        ("info", "info"),
        ("warning", "warning"),
        ("critical", "critical"),
    ]

    message = models.TextField()
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="info")
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.level}] {self.message[:50]}"