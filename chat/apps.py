from django.apps import AppConfig

class ChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat'

    def ready(self):
        import chat.signals  # noqa: F401 - registers the login/failed-login receivers

        # Confirms the resolved email configuration (backend/host/port/TLS/
        # SSL/timeout, never the password) at process startup, once per
        # worker - the fastest way to see in Render's own logs whether an
        # env var actually made it into Django's settings, without waiting
        # for a real password-reset request to find out. See
        # chat/services/email.py for the full incident writeup this is part
        # of the fix for.
        from chat.services.email import log_email_configuration
        log_email_configuration()