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
    # `role` must never be editable here: chat/permissions.py's
    # sync_django_flags() grants real Django is_superuser=True to Role.
    # SUPER_ADMIN+ (so django.contrib.admin itself keeps working for them),
    # which also makes them bypass every ModelAdmin permission check on this
    # site - without this, a Super Admin could edit their own (or anyone
    # else's) role to Role.OWNER directly from this change form, completely
    # bypassing the Owner-protection rule and the audited transfer_ownership
    # flow that chat/admin_views.py enforces as the only legitimate path to
    # ownership changes. readonly_fields is enforced for superusers too, so
    # this closes that path while leaving the field visible for inspection.
    readonly_fields = ("role",)
