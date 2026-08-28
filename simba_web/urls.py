from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import path, include
from django.views.generic.base import RedirectView
from chat import views, admin_views


def health_check(request):
    """Unauthenticated, dependency-light endpoint for Render's health check
    and any external uptime monitor - confirms the app process AND the
    database connection are both actually up, not just that Gunicorn is
    listening."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"status": "error", "detail": str(e)}, status=503)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),
    # Custom Super Admin Console - superuser-gated (see chat/admin_views.py's
    # superuser_required), deliberately separate from django.contrib.admin
    # above (left in place for direct DB inspection, but not what operators
    # use day-to-day).
    path('admin-console/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin-console/search/', admin_views.admin_quick_search, name='admin_quick_search'),
    path('admin-console/live/', admin_views.admin_live_platform, name='admin_live_platform'),
    path('admin-console/live/data/', admin_views.admin_live_platform_data, name='admin_live_platform_data'),
    path('admin-console/users/', admin_views.admin_users_list, name='admin_users_list'),
    path('admin-console/users/export/', admin_views.admin_users_export_csv, name='admin_users_export_csv'),
    path('admin-console/users/<int:user_id>/', admin_views.admin_user_detail, name='admin_user_detail'),
    path('admin-console/users/<int:user_id>/export/', admin_views.admin_export_user_data, name='admin_export_user_data'),
    path('admin-console/audit-log/', admin_views.admin_audit_log, name='admin_audit_log'),
    path('admin-console/audit-log/export/', admin_views.admin_audit_log_export_csv, name='admin_audit_log_export_csv'),
    path('admin-console/security/', admin_views.admin_security, name='admin_security'),
    path('admin-console/feature-flags/', admin_views.admin_feature_flags, name='admin_feature_flags'),
    path('admin-console/broadcasts/', admin_views.admin_broadcasts, name='admin_broadcasts'),
    path('admin-console/errors/', admin_views.admin_errors, name='admin_errors'),
    path('admin-console/errors/<int:error_id>/resolve/', admin_views.admin_error_resolve, name='admin_error_resolve'),
    path('admin-console/system-health/', admin_views.admin_system_health, name='admin_system_health'),
    path('admin-console/system-health/data/', admin_views.admin_system_health_data, name='admin_system_health_data'),
    path('admin-console/roles/', admin_views.admin_roles, name='admin_roles'),
    path('admin-console/reports/', admin_views.admin_reports, name='admin_reports'),
    path('admin-console/reports/<str:report_type>/', admin_views.admin_report_download, name='admin_report_download'),
    path('admin-console/ai-control/', admin_views.admin_ai_control, name='admin_ai_control'),
    path('admin-console/settings/', admin_views.admin_settings, name='admin_settings'),
    path('admin-console/live/logs/', admin_views.admin_live_log_stream, name='admin_live_log_stream'),
    path('favicon.ico', RedirectView.as_view(url='/static/favicon2.png', permanent=True)),
    # Recovery-code password reset (additional to allauth's own link-based
    # reset flow below, which is untouched) - registered before the allauth
    # include so these exact paths always resolve here first.
    path('accounts/forgot-password/', views.forgot_password, name='forgot_password'),
    path('accounts/verify-recovery-code/', views.verify_recovery_code, name='verify_recovery_code'),
    path('accounts/reset-password-recovery/', views.reset_password_recovery, name='reset_password_recovery'),
    path('accounts/recovery-code/', views.recovery_code_display, name='recovery_code_display'),
    path('accounts/recovery-code/regenerate/', views.regenerate_recovery_code, name='regenerate_recovery_code'),
    path('accounts/', include('allauth.urls')),
    path('verification/resend/', views.resend_verification_email, name='resend_verification_email'),
    path('verification/status/', views.verification_status, name='verification_status'),
    path('accounts/email-verified/', views.email_verified_success, name='email_verified_success'),
    path('', views.chat_home, name='home'),
    path('ask/', views.ask_ai, name='ask'),
    path('pin_session/<int:session_id>/', views.pin_session, name='pin_session'),
    path('delete_session/<int:session_id>/', views.delete_session, name='delete_session'),
    path('rename_session/<int:session_id>/', views.rename_session, name='rename_session'),
    path('sessions/<int:session_id>/archive/', views.toggle_archive_session, name='toggle_archive_session'),
    path('sessions/<int:session_id>/favorite/', views.toggle_favorite_session, name='toggle_favorite_session'),
    path('sessions/<int:session_id>/duplicate/', views.duplicate_session, name='duplicate_session'),
    path('sessions/<int:session_id>/folder/', views.set_session_folder, name='set_session_folder'),
    path('folders/summary/', views.folders_summary, name='folders_summary'),
    path('folders/create/', views.create_folder, name='create_folder'),
    path('folders/rename/', views.rename_folder, name='rename_folder'),
    path('folders/delete/', views.delete_folder, name='delete_folder'),
    path('folders/color/', views.set_folder_color, name='set_folder_color'),
    path('sessions/<int:session_id>/color/', views.set_session_color, name='set_session_color'),
    path('sessions/bulk-action/', views.bulk_session_action, name='bulk_session_action'),
    path('sessions/search/', views.search_chats, name='search_chats'),
    path('ask_ai/', views.ask_ai, name='ask_ai'),
    path('update_model/', views.update_model_session, name='update_model'),
    path("upload/", views.upload_file),
    path('attachments/<uuid:attachment_id>/', views.serve_attachment, name='serve_attachment'),
    path('attachments/<uuid:attachment_id>/content/', views.attachment_content, name='attachment_content'),
    path('settings/', views.profile_settings, name='profile_settings'),
    path('settings/timezone/', views.set_timezone, name='set_timezone'),
    path('account/sessions/<int:session_id>/logout/', views.logout_session, name='logout_session'),
    path('account/sessions/logout-all/', views.logout_all_sessions, name='logout_all_sessions'),
    path('account/memory/clear/', views.clear_memory, name='clear_memory'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('session/<int:session_id>/active-leaf/', views.session_active_leaf, name='session_active_leaf'),
    path('session/<int:session_id>/suggest-followups/', views.session_suggest_followups, name='session_suggest_followups'),
    path('session/<int:session_id>/related/', views.session_related_conversations, name='session_related_conversations'),
    path('messages/<int:message_id>/siblings/', views.message_siblings, name='message_siblings'),
    path('messages/<int:message_id>/regenerate/', views.regenerate_message, name='regenerate_message'),
    path('messages/<int:message_id>/edit/', views.edit_message, name='edit_message'),
    path('messages/<int:message_id>/switch-branch/', views.switch_branch, name='switch_branch'),
    path('messages/<int:message_id>/toggle-favorite/', views.toggle_favorite_image, name='toggle_favorite_image'),
    path('messages/<int:message_id>/bookmark/', views.bookmark_message, name='bookmark_message'),
    path('messages/<int:message_id>/info/', views.message_info, name='message_info'),
    path('messages/<int:message_id>/bookmark/label/', views.set_bookmark_label, name='set_bookmark_label'),
    path('bookmarks/', views.bookmarks_list, name='bookmarks_list'),
    path('prompts/', views.saved_prompts_list, name='saved_prompts_list'),
    path('prompts/create/', views.create_saved_prompt, name='create_saved_prompt'),
    path('prompts/<int:prompt_id>/update/', views.update_saved_prompt, name='update_saved_prompt'),
    path('prompts/<int:prompt_id>/delete/', views.delete_saved_prompt, name='delete_saved_prompt'),
    path('prompts/<int:prompt_id>/use/', views.use_saved_prompt, name='use_saved_prompt'),
    path('prompts/recent/', views.recent_prompts, name='recent_prompts'),
    path('messages/<int:message_id>/delete/', views.delete_message, name='delete_message'),
    path('messages/<int:message_id>/continue/', views.continue_message, name='continue_message'),
    path('agent/confirm/', views.agent_confirm_action, name='agent_confirm_action'),
    path('system_stats/', views.system_stats, name='system_stats'),
    path('update_reaction/', views.update_reaction, name='update_reaction'),

    # Desktop Agent API Endpoints (Phase 1: Cloud ↔ Local Desktop Agent Connection)
    path('api/agent/connect/', views.agent_connect_view, name='agent_connect'),
    path('api/agent/poll/', views.agent_poll_view, name='agent_poll'),
    path('api/agent/result/', views.agent_result_view, name='agent_result'),
    path('api/agent/heartbeat/', views.agent_heartbeat_view, name='agent_heartbeat'),
    path('api/agent/disconnect/', views.agent_disconnect_view, name='agent_disconnect'),
    path('api/agent/status/', views.agent_status_view, name='agent_status'),
    path('api/agent/token/regenerate/', views.agent_regenerate_token_view, name='agent_regenerate_token'),
]