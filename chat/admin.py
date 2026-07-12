from django.contrib import admin

from chat.models import ChatSession, ChatMessage, UserProfile


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("user_query", "ai_response", "timestamp", "latency", "extra_data")
    can_delete = False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "is_pinned", "created_at")
    list_filter = ("is_pinned", "created_at")
    search_fields = ("title", "user__username", "user__email")
    inlines = [ChatMessageInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "user_query", "timestamp", "latency")
    list_filter = ("timestamp",)
    search_fields = ("user_query", "ai_response")
    readonly_fields = ("timestamp",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "default_model", "theme", "memory_enabled", "updated_at")
    list_filter = ("theme", "memory_enabled", "notifications_enabled")
    search_fields = ("user__username", "user__email", "display_name")
