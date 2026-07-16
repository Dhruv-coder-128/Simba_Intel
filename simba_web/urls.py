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
    path('admin-console/users/', admin_views.admin_users_list, name='admin_users_list'),
    path('admin-console/users/<int:user_id>/', admin_views.admin_user_detail, name='admin_user_detail'),
    path('admin-console/users/<int:user_id>/export/', admin_views.admin_export_user_data, name='admin_export_user_data'),
    path('admin-console/audit-log/', admin_views.admin_audit_log, name='admin_audit_log'),
    path('admin-console/security/', admin_views.admin_security, name='admin_security'),
    path('admin-console/feature-flags/', admin_views.admin_feature_flags, name='admin_feature_flags'),
    path('admin-console/broadcasts/', admin_views.admin_broadcasts, name='admin_broadcasts'),
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
    path('ask_ai/', views.ask_ai, name='ask_ai'),
    path('update_model/', views.update_model_session, name='update_model'),
    path('system_stats/', views.system_stats, name='system_stats'),
    path("upload/", views.upload_file),
    path('settings/', views.profile_settings, name='profile_settings'),
    path('account/sessions/<int:session_id>/logout/', views.logout_session, name='logout_session'),
    path('account/sessions/logout-all/', views.logout_all_sessions, name='logout_all_sessions'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('session/<int:session_id>/active-leaf/', views.session_active_leaf, name='session_active_leaf'),
    path('messages/<int:message_id>/siblings/', views.message_siblings, name='message_siblings'),
    path('messages/<int:message_id>/regenerate/', views.regenerate_message, name='regenerate_message'),
    path('messages/<int:message_id>/edit/', views.edit_message, name='edit_message'),
    path('messages/<int:message_id>/switch-branch/', views.switch_branch, name='switch_branch'),
    path('messages/<int:message_id>/toggle-favorite/', views.toggle_favorite_image, name='toggle_favorite_image'),
]