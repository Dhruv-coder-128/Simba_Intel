from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions', null=True, blank=True)
    title = models.CharField(max_length=255, default="New Chat")
    created_at = models.DateTimeField(auto_now_add=True)
    is_pinned = models.BooleanField(default=False)

    def __str__(self):
        return self.title

class ChatMessage(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    user_query = models.TextField()
    ai_response = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    latency = models.FloatField(null=True, blank=True)
    # New field for image/extra data (JSON)
    extra_data = models.JSONField(null=True, blank=True)


class UserProfile(models.Model):
    THEME_CHOICES = [
        ("cyberpunk", "Cyberpunk (default)"),
        ("midnight-purple", "Midnight Purple"),
        ("matrix-green", "Matrix Green"),
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