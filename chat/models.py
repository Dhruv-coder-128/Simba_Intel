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

    def __str__(self):
        return f"Profile({self.user})"

    @classmethod
    def get_or_create_for(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile


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