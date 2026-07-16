from django.apps import AppConfig

class ChatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chat'

    def ready(self):
        import chat.signals  # noqa: F401 - registers the login/failed-login receivers

        # Confirms the resolved email configuration (backend, whether
        # RESEND_API_KEY is set, never its value) at process startup, once
        # per worker - the fastest way to see in Render's own logs whether
        # an env var actually made it into Django's settings, without
        # waiting for a real password-reset request to find out. See
        # chat/services/email.py and chat/services/resend_backend.py for
        # the full SMTP-to-Resend migration this is part of.
        from chat.services.email import log_email_configuration
        log_email_configuration()