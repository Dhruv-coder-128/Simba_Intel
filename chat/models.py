import secrets
import uuid

from django.contrib.auth.hashers import check_password, make_password
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
    COLOR_CHOICES = [
        ('', 'None'), ('red', 'Red'), ('orange', 'Orange'), ('yellow', 'Yellow'),
        ('green', 'Green'), ('blue', 'Blue'), ('purple', 'Purple'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions', null=True, blank=True)
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    is_pinned = models.BooleanField(default=False)
    # Session-level organization (distinct from Message.extra_data's
    # per-image "favorited" flag, which favorites one generated image, not
    # a whole conversation). Archiving is a soft hide, not a delete - an
    # archived session is excluded from the default sidebar list but never
    # removed; only delete_session actually destroys data.
    is_archived = models.BooleanField(default=False)
    is_favorite = models.BooleanField(default=False)
    # Flat, not nested - there's no existing folder hierarchy anywhere in
    # this app to build on, and a full nested-tree UI (create/rename/move/
    # reorder folders, drag-and-drop between them) is a much larger feature
    # than one flat grouping label. A blank folder means "no folder".
    folder = models.CharField(max_length=100, blank=True, default='')
    color_label = models.CharField(max_length=10, choices=COLOR_CHOICES, blank=True, default='')
    # The current tip of the active branch in this session's message tree.
    # NULL means the session has no Message-tree history yet (e.g. legacy
    # sessions before this field existed, or a brand new session).
    active_leaf = models.ForeignKey(
        'Message', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )

    # --- AI Memory (Part 2) ---
    # A running, AI-generated compression of everything before the most
    # recent window of turns - see chat/services/conversation_memory.py.
    # summary_message_count is how many Message rows existed at the time
    # `summary` was last generated, so a later check can cheaply tell
    # "how much new content has accumulated since" without re-summarizing
    # from scratch on every single turn.
    summary = models.TextField(blank=True, default='')
    summary_message_count = models.PositiveIntegerField(default=0)
    # Cross-chat fact extraction (gated on UserProfile.memory_enabled) is
    # attempted at most once per session, tracked here - a fixed one-shot
    # rather than continuous extraction, since re-scanning the same early
    # turns on every later message would just re-derive the same handful of
    # durable facts at extra cost for no benefit.
    facts_extracted = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_archived', '-created_at']),
            models.Index(fields=['user', 'folder']),
        ]

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


class MessageAttachment(models.Model):
    """Stores uploaded file attachments associated with a user message and session."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments', null=True, blank=True)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='attachments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='attachments/%Y/%m/%d/')
    original_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True, default='')
    file_type = models.CharField(max_length=20, default='file')  # 'image', 'pdf', 'text', 'code', 'file'
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['message']),
        ]

    def __str__(self):
        return f"{self.original_name} ({self.file_size} bytes)"

    def delete(self, *args, **kwargs):
        if self.file:
            try:
                self.file.delete(save=False)
            except Exception:
                pass
        super().delete(*args, **kwargs)

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.original_name,
            "size": self.file_size,
            "mime_type": self.mime_type,
            "file_type": self.file_type,
            "url": f"/attachments/{self.id}/",
            "content_url": f"/attachments/{self.id}/content/",
        }


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
        # Part 5 (Settings redesign task) - expanded theme set.
        ("cyber-orange", "Cyber Orange"),
        ("neon-green", "Neon Green"),
        ("midnight-blue", "Midnight Blue"),
        ("purple-matrix", "Purple Matrix"),
        ("crimson-red", "Crimson Red"),
        ("arctic-white", "Arctic White"),
        ("oled-black", "OLED Black"),
        ("emerald", "Emerald"),
        ("royal-gold", "Royal Gold"),
    ]

    # --- Appearance (Part 6) --- each rendered as a data-* attribute on
    # <html> (same mechanism as data-theme already uses) so plain CSS rules
    # do the actual work - no per-page JS is needed to make these apply.
    # Blank accent_override means "use the active theme's own accent",
    # letting a user layer a personal accent on top of any theme instead of
    # only ever getting the theme's built-in one.
    ACCENT_OVERRIDE_CHOICES = [
        ("", "Theme default"),
        ("cyan", "Cyan"),
        ("green", "Green"),
        ("blue", "Blue"),
        ("purple", "Purple"),
        ("pink", "Pink"),
        ("orange", "Orange"),
        ("red", "Red"),
        ("gold", "Gold"),
    ]
    DENSITY_CHOICES = [
        ("comfortable", "Comfortable"),
        ("compact", "Compact"),
    ]
    CARD_RADIUS_CHOICES = [
        ("sharp", "Sharp"),
        ("rounded", "Rounded (default)"),
        ("soft", "Soft"),
    ]
    ANIMATION_LEVEL_CHOICES = [
        ("full", "Full (default)"),
        ("reduced", "Reduced"),
        ("none", "None"),
    ]
    GLASS_INTENSITY_CHOICES = [
        ("off", "Off"),
        ("light", "Light"),
        ("medium", "Medium (default)"),
        ("high", "High"),
    ]

    REGISTRATION_SOURCE_CHOICES = [
        ("email", "Email"),
        ("google", "Google"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    display_name = models.CharField(max_length=100, blank=True)
    avatar_url = models.URLField(blank=True)
    default_model = models.CharField(max_length=50, default='ox-alpha')
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='cyberpunk')
    accent_override = models.CharField(max_length=20, choices=ACCENT_OVERRIDE_CHOICES, blank=True, default='')
    density = models.CharField(max_length=20, choices=DENSITY_CHOICES, default='comfortable')
    card_radius = models.CharField(max_length=20, choices=CARD_RADIUS_CHOICES, default='rounded')
    animation_level = models.CharField(max_length=20, choices=ANIMATION_LEVEL_CHOICES, default='full')
    glass_intensity = models.CharField(max_length=20, choices=GLASS_INTENSITY_CHOICES, default='medium')
    memory_enabled = models.BooleanField(default=False)
    notifications_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- SIMBA Desktop Agent Connection (Phase 1) ---
    # Secret authentication token and metadata for the user's local Windows PC agent
    agent_token = models.CharField(max_length=64, blank=True, default='', db_index=True)
    agent_device_name = models.CharField(max_length=100, blank=True, default='')
    agent_platform = models.CharField(max_length=100, blank=True, default='')
    agent_last_seen = models.DateTimeField(null=True, blank=True)

    def get_or_create_agent_token(self) -> str:
        """Returns the user's existing desktop agent token or generates a secure new one."""
        if not self.agent_token:
            import secrets
            self.agent_token = f"simba_at_{secrets.token_hex(24)}"
            self.save(update_fields=['agent_token'])
        return self.agent_token

    def regenerate_agent_token(self) -> str:
        """Regenerates the desktop agent token, invalidating previous desktop sessions."""
        import secrets
        self.agent_token = f"simba_at_{secrets.token_hex(24)}"
        self.save(update_fields=['agent_token'])
        return self.agent_token

    # --- Timezone (single source of truth for every timestamp in the app -
    # see chat.middleware.TimezoneMiddleware) ---
    # timezone_auto=True means the browser-detected IANA name (posted by
    # chat.html on load) is still free to update this field; saving an
    # explicit choice from Settings > General flips it to False so a
    # deliberate pick never gets silently overwritten by auto-detection.
    timezone = models.CharField(max_length=64, default='UTC')
    timezone_auto = models.BooleanField(default=True)

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
        # Tries the reverse accessor first rather than a fresh `filter(user=
        # user).first()` query: if anything earlier in this same request
        # (TimezoneMiddleware, a permissions check, this same method called
        # twice) already touched `user.profile`, Django cached it on `user`
        # and this is a free in-memory hit - a real, common case, since
        # TimezoneMiddleware reads it on every authenticated request before
        # any view runs. Falls through to the same query as before on a
        # genuine cache miss, so nothing gets slower.
        try:
            return user.profile
        except cls.DoesNotExist:
            pass
        if user.is_superuser:
            initial_role = Role.SUPER_ADMIN
        elif user.is_staff:
            initial_role = Role.ADMIN
        else:
            initial_role = Role.USER
        profile, _ = cls.objects.get_or_create(user=user, defaults={"role": initial_role})
        # Primes the same cache for the rest of this request - the RBAC/
        # timezone context processors and any later code on `user` (not
        # necessarily calling get_or_create_for again) all read `user.
        # profile` too, and would otherwise re-query for the exact same row.
        user.profile = profile
        return profile

    @property
    def is_suspended(self):
        return bool(self.suspended_until and self.suspended_until > timezone.now())


class UserFact(models.Model):
    """Cross-chat memory (Part 2) - a durable fact extracted from one
    conversation and reused as light context in future, unrelated
    conversations. Only ever written to when UserProfile.memory_enabled is
    True (see conversation_memory.extract_and_store_facts) and only ever
    read from under the same condition (get_user_memory_context) - flipping
    the toggle off stops both new writes and any use of what's already
    stored, and the Settings > Privacy "Clear memory" action gives the user
    a way to delete everything here outright."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='facts')
    fact = models.TextField()
    source_session = models.ForeignKey(ChatSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', '-created_at'])]
        ordering = ['-created_at']

    def __str__(self):
        return f"Fact({self.user}): {self.fact[:60]}"


class SavedPrompt(models.Model):
    """Prompt Library (Part 5) - Saved/Favorite/Templates/Categories all
    live on this one model rather than as separate tables: a "template" is
    just a saved prompt filed under a category, a "favorite" is a flag, and
    "recent"/"history" don't need storage at all - those read directly from
    the user's own past Message(role='user') rows (see recent_prompts view),
    since that history already exists and duplicating it here would just be
    two copies of the same text drifting apart."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_prompts')
    title = models.CharField(max_length=100)
    content = models.TextField()
    # Free text, not a fixed choice list - mirrors ChatSession.folder's own
    # reasoning (a blank category means "uncategorized"), so a user's own
    # label always works instead of forcing a fit into a fixed set.
    category = models.CharField(max_length=50, blank=True, default='')
    is_favorite = models.BooleanField(default=False)
    use_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['user', '-created_at'])]
        ordering = ['-is_favorite', '-updated_at']

    def __str__(self):
        return f"{self.title} ({self.user})"


class Folder(models.Model):
    """Folder metadata (name + color) for the sidebar's chat organization.

    Membership deliberately stays on ChatSession.folder (a plain string),
    NOT a ForeignKey here: this model is pure metadata layered on top of the
    pre-existing string-based folders, so every already-filed chat keeps
    working with zero data migration and a folder can exist with no metadata
    row at all (it just renders with the default colour). Rename therefore
    updates this row AND bulk-updates the matching ChatSession.folder
    strings; delete removes this row AND unfiles its chats (folder='') but
    never deletes the chats themselves - see the folder views for the full
    workflow.

    Flat, not nested - same reasoning as ChatSession.folder's own comment.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='folders')
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=10, choices=ChatSession.COLOR_CHOICES, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'name')]
        ordering = ['name']

    def __str__(self):
        return f"Folder({self.user}): {self.name}"


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
    # False marks a failed call (see usage.record_failure) - Part 7's
    # success/error rate analytics reads this. check_rate_limit and
    # check_daily_limit both explicitly filter to success=True: a call that
    # never got a response must never eat into the user's rate/daily quota,
    # or a provider outage would double-punish them (no answer AND a
    # consumed request) instead of just failing gracefully.
    success = models.BooleanField(default=True)
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


# No 0/O/1/I - all four are easy to mis-transcribe by hand (which is the
# whole point of a recovery code: written down or downloaded, then typed
# back in later from a screen or a piece of paper, not copy-pasted from a
# link like the old emailed OTP was).
_RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_raw_recovery_code() -> str:
    groups = ["".join(secrets.choice(_RECOVERY_CODE_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "SIMBA-" + "-".join(groups)


class RecoveryCode(models.Model):
    """Replaces the old emailed-OTP password reset entirely: local accounts
    get exactly one recovery code (shown once, at signup or on regeneration -
    see chat/signals.py and chat/views.py's recovery_code_display), and
    forgot_password/verify_recovery_code/reset_password_recovery in
    chat/views.py check a submitted code against it. Google-only accounts
    (no usable local password - see User.has_usable_password()) never get
    one; they recover through Google itself.

    Only ever stores make_password()'s hash, never the raw code - the raw
    value exists only in memory for the single request that generates it,
    and briefly in the session so the one-time display page can show it
    (see recovery_code_display), never persisted to the database anywhere."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='recovery_code')
    code_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"RecoveryCode({self.user})"

    def verify(self, raw_code: str) -> bool:
        return check_password(raw_code, self.code_hash)

    @classmethod
    def generate_for(cls, user):
        """Creates (or overwrites - a user only ever has one) this user's
        recovery code. Returns (RecoveryCode, raw_code); the caller is
        responsible for showing raw_code to the user exactly once and never
        storing it anywhere itself."""
        raw_code = _generate_raw_recovery_code()
        obj, _created = cls.objects.update_or_create(
            user=user, defaults={"code_hash": make_password(raw_code)},
        )
        return obj, raw_code


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
        ("export_users_csv", "export_users_csv"),
        ("export_audit_log_csv", "export_audit_log_csv"),
        ("error_resolved", "error_resolved"),
        ("report_generated", "report_generated"),
        ("warn_user", "warn_user"),
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
    # Display style, independent of `level` (which is about severity/color,
    # not placement): a banner is the existing, always-on-top-of-page
    # behavior; a popup is a one-time modal a user must notice and close.
    # Dismissible is tracked client-side only (localStorage, keyed by this
    # row's id) - deliberately not a per-user DB row, since "has every user
    # dismissed this" isn't something any current page needs to know, and a
    # new dismissal table for that would outlive the broadcast itself.
    is_popup = models.BooleanField(default=False)
    dismissible = models.BooleanField(default=True)
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


class ErrorLog(models.Model):
    """Application-level error tracking for the admin console's Error
    Center - deliberately separate from SecurityEvent (auth/security
    signals) and AdminAuditLog (operator actions). Every AI provider call
    already funnels its failures through chat.utils.logger.SimbaLogger.
    log_request(error=...) - that's the single choke point this model is
    fed from (see SimbaLogger), plus a got_request_exception signal
    receiver (chat/signals.py) for anything unhandled that reaches Django's
    own 500 handler.

    Duplicate errors are grouped, not stored one row per occurrence: the
    same (category, message) while unresolved increments `count` and bumps
    `last_seen` instead of creating a new row. Marking a group resolved
    starts a fresh row the next time that exact error recurs, rather than
    silently reopening a closed one - the same convention most bug trackers
    use for "this happened again after I thought I fixed it"."""

    CATEGORY_CHOICES = [
        ("chat_provider", "Chat Provider"),
        ("image_provider", "Image Provider"),
        ("vision_provider", "Vision Provider"),
        ("unhandled_exception", "Unhandled Exception"),
    ]

    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    message = models.TextField()
    detail = models.TextField(blank=True)
    count = models.PositiveIntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        indexes = [
            models.Index(fields=['-last_seen']),
            models.Index(fields=['category', 'resolved']),
        ]
        ordering = ['-last_seen']

    def __str__(self):
        return f"ErrorLog({self.category}, x{self.count}, resolved={self.resolved})"

    @classmethod
    def record(cls, category: str, message: str, detail: str = ""):
        # Keyed on the first 200 chars so two errors differing only by a
        # dynamic id/timestamp embedded in the message still group together
        # in practice, without needing real message-template extraction.
        key_message = (message or "")[:200]
        obj, created = cls.objects.get_or_create(
            category=category, message=key_message, resolved=False,
            defaults={'detail': detail},
        )
        if not created:
            obj.count = models.F('count') + 1
            if detail:
                obj.detail = detail
            obj.save(update_fields=['count', 'detail', 'last_seen'])
        return obj