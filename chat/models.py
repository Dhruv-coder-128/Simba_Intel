import random
from datetime import timedelta

from django.core.cache import cache
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class Role(models.TextChoices):
    """SIMBA_INTEL's own permission hierarchy - deliberately independent of
    Django's is_staff/is_superuser (those stay wired for Django admin
    compatibility only, per chat/permissions.py's docstring). Ordered
    highest-privilege first to match the org-chart in the spec; the actual
    numeric ranking used for "at least this role" checks lives in
    chat/permissions.py's ROLE_LEVEL, not here, so adding a new role later
    never requires touching comparison logic in more than one place."""

    OWNER = "owner", "Owner"
    SUPER_ADMIN = "super_admin", "Super Admin"
    ADMIN = "admin", "Admin"
    MODERATOR = "moderator", "Moderator"
    VERIFIED = "verified", "Verified User"
    USER = "user", "User"


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

    REGISTRATION_SOURCE_CHOICES = [
        ("email", "Email"),
        ("google", "Google"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=100, blank=True)
    avatar_url = models.URLField(blank=True)
    default_model = models.CharField(max_length=50, default='cyber-max')
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='cyberpunk')
    memory_enabled = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- RBAC ---
    # The single source of truth for every SIMBA_INTEL permission check -
    # see chat/permissions.py. is_staff/is_superuser (on auth.User) are left
    # alone for Django/allauth/django.contrib.admin compatibility only and
    # are kept in sync as a side effect of role changes, never read by any
    # SIMBA_INTEL permission check itself.
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER, db_index=True)

    # --- Account/security snapshot (admin-console prep) ---
    # Deliberately a snapshot of the *latest* login, not a full history -
    # SecurityEvent already is the append-only history this is drawn from;
    # these fields exist purely so a "last login was X from Y" fact doesn't
    # need a query against that log every time it's displayed.
    registration_source = models.CharField(max_length=20, choices=REGISTRATION_SOURCE_CHOICES, default='email')
    email_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_device = models.CharField(max_length=100, blank=True, default='Unknown Device')
    last_login_browser = models.CharField(max_length=100, blank=True, default='Unknown Browser')
    last_login_os = models.CharField(max_length=100, blank=True, default='Unknown OS')

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

    # Soft delete: the account row itself is never removed (chat history,
    # usage records, and audit trail all still need somewhere to point) -
    # deletion just means blocked login + hidden from the default user list,
    # exactly reversible via "Restore User".
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # --- Per-user usage limits (admin console prep) ---
    # Daily caps, reset at local midnight (checked against created_at__date,
    # not a rolling 24h window) - separate from and on top of
    # chat/services/usage.py's check_rate_limit, which guards against short
    # bursts (30/minute) regardless of these daily totals. unlimited_usage
    # bypasses all four caps below entirely for accounts that need it
    # (internal testing, VIP accounts) without deleting/faking limit values.
    unlimited_usage = models.BooleanField(default=False)
    daily_chat_limit = models.PositiveIntegerField(default=50)
    daily_image_limit = models.PositiveIntegerField(default=10)
    daily_vision_limit = models.PositiveIntegerField(default=10)
    daily_token_limit = models.PositiveIntegerField(default=100000)

    def __str__(self):
        return f"Profile({self.user})"

    @classmethod
    def get_or_create_for(cls, user):
        """Profiles are created lazily (on first real use, not at signup),
        so this is the one place a brand-new profile's initial role gets
        decided - mirrors chat/migrations/0023_promote_owner_and_backfill_
        roles.py's own is_staff/is_superuser -> role mapping, so an account
        that's superuser/staff via the *standard* Django mechanism
        (createsuperuser, or a pre-RBAC fixture/test) still starts with
        working admin-console access instead of silently landing on
        Role.USER the moment RBAC is what actually gates that console. This
        only ever applies to a profile's initial creation - it never
        touches role on an existing row, so it can't undo a deliberate
        demotion made through the admin console afterward."""
        profile = cls.objects.filter(user=user).first()
        if profile is not None:
            return profile
        if user.is_superuser:
            initial_role = Role.SUPER_ADMIN
        elif user.is_staff:
            initial_role = Role.ADMIN
        else:
            initial_role = Role.USER
        profile, _ = cls.objects.get_or_create(user=user, defaults={"role": initial_role})
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
        ("feature_flag_create", "feature_flag_create"),
        ("broadcast_create", "broadcast_create"),
        ("broadcast_deactivate", "broadcast_deactivate"),
        ("delete_account", "delete_account"),
        ("restore_account", "restore_account"),
        ("export_user_data", "export_user_data"),
        ("update_usage_limits", "update_usage_limits"),
        ("ownership_transfer", "ownership_transfer"),
        ("blocked_attempt", "blocked_attempt"),
    ]

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='admin_actions_taken')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='admin_actions_received')
    detail = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser = models.CharField(max_length=100, blank=True, default='Unknown Browser')
    success = models.BooleanField(default=True)
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
    # ip_address stays nullable (None is the correct representation of
    # "unknown" for an IP-typed column - a placeholder string can't go in
    # here) - display code falls back to "Unknown IP" at render time. The
    # text fields below all get a real default: chat/utils/device.py's
    # parse_client_info() already always returns a concrete "Unknown ..."
    # string rather than blank, but the model-level defaults are a second
    # line of defense against any future insert that forgets to pass one.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')
    browser = models.CharField(max_length=100, blank=True, default='Unknown Browser')
    device = models.CharField(max_length=100, blank=True, default='Unknown Device')
    os = models.CharField(max_length=100, blank=True, default='Unknown OS')
    # No geo-IP lookup is wired in anywhere in this project - this is a
    # placeholder for that future integration, always "Unknown Location"
    # until one exists, rather than a column that silently sits unused.
    location = models.CharField(max_length=100, blank=True, default='Unknown Location')
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
    """Simple on/off switches read at request time. `is_enabled()` sits on
    the hottest possible path - MaintenanceModeMiddleware calls it before
    anything else runs on every single request - so reads go through a
    short-TTL cache instead of hitting the DB every time. save()/delete()
    clear the cache immediately, so a toggle still takes effect right away
    in the process that made the change; the TTL is just a safety net
    bounding how long any *other* worker process can serve a stale value."""

    CACHE_TTL_SECONDS = 10

    key = models.SlugField(max_length=50, unique=True)
    enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key} = {self.enabled}"

    @staticmethod
    def _cache_key(key):
        return f"featureflag:{key}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(self._cache_key(self.key))

    def delete(self, *args, **kwargs):
        key = self.key
        super().delete(*args, **kwargs)
        cache.delete(self._cache_key(key))

    @classmethod
    def is_enabled(cls, key, default=True):
        cache_key = cls._cache_key(key)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        flag = cls.objects.filter(key=key).first()
        if flag is None:
            return default
        cache.set(cache_key, flag.enabled, cls.CACHE_TTL_SECONDS)
        return flag.enabled


class UserSession(models.Model):
    """One row per active login session, keyed to Django's own session_key -
    powers the Account Security page's device list and the logout-this-
    device/logout-all-devices actions. Django's built-in Session model has
    no user FK or metadata columns (session_data is an opaque encoded blob),
    which is why admin_views.py's _force_logout_user has to decode every
    live session to find a user's own - this exists so a user's own security
    page doesn't need to pay that same O(all active sessions) cost just to
    list their own devices.

    Written once, at login (see chat/signals.py) - deliberately not touched
    on every request (no "last seen" freshness tracking), since that would
    mean a DB write on every single page view for a nice-to-have timestamp.
    A session row simply represents "was active as of this login"; whether
    it's still valid at all is Django's own Session table's job (expiry),
    not this model's."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tracked_sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')
    browser = models.CharField(max_length=100, blank=True, default='Unknown Browser')
    device = models.CharField(max_length=100, blank=True, default='Unknown Device')
    os = models.CharField(max_length=100, blank=True, default='Unknown OS')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', '-created_at'])]
        ordering = ['-created_at']

    def __str__(self):
        return f"Session({self.user}, {self.device}, {self.browser})"


class Broadcast(models.Model):
    """A single active banner shown to every logged-in user - maintenance
    notices, incident updates, announcements. Only one is meant to be
    .active at a time; the admin console enforces that on save.

    starts_at/ends_at are optional scheduling bounds layered on top of the
    existing `active` flag rather than replacing it: `active=False` is still
    an immediate, unconditional off-switch (what the admin console's
    "Deactivate" button flips), while starts_at/ends_at let a broadcast be
    created now but only actually show (or stop showing) at a specific time
    without an admin needing to be online to flip it."""

    LEVEL_CHOICES = [
        ("info", "info"),
        ("warning", "warning"),
        ("critical", "critical"),
    ]

    message = models.TextField()
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="info")
    active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.level}] {self.message[:50]}"

    @property
    def status(self):
        """One of "expired", "scheduled", "inactive", "active" - the single
        source of truth the admin console and the live-site banner both use,
        so "is this actually showing right now" is never computed two
        different ways in two different places."""
        if not self.active:
            return "inactive"
        now = timezone.now()
        if self.ends_at and now >= self.ends_at:
            return "expired"
        if self.starts_at and now < self.starts_at:
            return "scheduled"
        return "active"

    def is_currently_visible(self):
        return self.status == "active"