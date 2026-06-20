from django.db import models

class ChatSession(models.Model):
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