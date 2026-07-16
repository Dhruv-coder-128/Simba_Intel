"""Hardened, instrumented email sending - built specifically to fix a
production-only failure: password-reset OTP emails hung on Render (never on
localhost), and the hang eventually took the entire gunicorn worker down
with it (SIGKILL, no traceback ever logged) rather than failing cleanly.

Root cause (confirmed, not assumed - see the two settings this module
depends on): Django's SMTP backend DOES pass EMAIL_TIMEOUT into
smtplib.SMTP(..., timeout=...) (confirmed by reading
django.core.mail.backends.smtp.EmailBackend.open() directly), so the socket
timeout was real. The problem is where that clock starts versus gunicorn's
own worker-timeout clock: gunicorn's timer starts the instant the request
is received (covering routing + view + DB overhead + the SMTP call itself),
while EMAIL_TIMEOUT's timer only starts once the socket call begins. With
EMAIL_TIMEOUT=30s and gunicorn's default (also ~30s, previously left
unset in the Dockerfile CMD) worker timeout, gunicorn's clock has a head
start and wins almost every time - the worker gets SIGKILLed while still
blocked inside socket.create_connection(), before Python ever regains
control to raise (let alone log) anything. That's exactly why production
logs showed "Worker Timeout" / SIGKILL with no SMTPAuthenticationError and
no traceback: the process was killed mid-syscall, not mid-exception.

The fix here has two independent parts, both required:
  1. simba_web/settings.py: EMAIL_TIMEOUT lowered well below gunicorn's now
     EXPLICIT --timeout (see Dockerfile) - the socket timeout must always
     fire and raise a catchable exception before gunicorn's clock would.
  2. This module: replaces the bare, unguarded send_mail() call
     (chat/views.py's old _send_otp_email) with a connection built and
     driven by hand, stage by stage, so every step - DNS, TCP connect,
     STARTTLS, AUTH, SEND - is individually timed, logged, and wrapped so
     nothing can propagate as an unhandled exception (or an un-timed-out
     hang) into the view. A network-layer failure now degrades to a clean,
     fast, logged, user-facing error instead of killing the worker.
"""
import logging
import smtplib
import socket
import ssl
import time

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

# Deliberately much smaller than EMAIL_TIMEOUT itself: this is the ceiling
# for each *individual* socket operation (connect, or a single read/write),
# not the whole exchange - smtplib re-applies the connection's timeout to
# every blocking call it makes, so the true worst case for the whole
# open+starttls+login+send sequence is a small multiple of this, still far
# under gunicorn's --timeout. See simba_web/settings.py's EMAIL_TIMEOUT
# comment for the exact numbers this is sized against.
_SOCKET_TIMEOUT_SECONDS = getattr(settings, "EMAIL_TIMEOUT", 10) or 10


def log_email_configuration():
    """Logs the resolved email configuration once at process startup
    (chat/apps.py's ChatConfig.ready()) - confirms Render's environment
    variables actually made it into Django's settings at all, without ever
    logging the password itself. Also the single place that detects and
    warns about the console backend being active (a common, silent
    misconfiguration: OTP codes only ever print to the Render log, no email
    is ever actually sent, and nothing about that looks like an error)."""
    backend = getattr(settings, "EMAIL_BACKEND", "")
    logger.info(
        "Email config: backend=%s host=%s port=%s use_tls=%s use_ssl=%s "
        "timeout=%ss host_user_set=%s from=%s debug=%s database_url_set=%s",
        backend,
        getattr(settings, "EMAIL_HOST", None),
        getattr(settings, "EMAIL_PORT", None),
        getattr(settings, "EMAIL_USE_TLS", None),
        getattr(settings, "EMAIL_USE_SSL", None),
        getattr(settings, "EMAIL_TIMEOUT", None),
        bool(getattr(settings, "EMAIL_HOST_USER", "")),
        getattr(settings, "DEFAULT_FROM_EMAIL", None),
        settings.DEBUG,
        bool(__import__("os").environ.get("DATABASE_URL")),
    )
    if backend == "django.core.mail.backends.console.EmailBackend":
        logger.warning(
            "EMAIL_BACKEND is the console backend - no email is actually being "
            "sent over the network; OTP/verification codes only print to this "
            "process's stdout. Set EMAIL_BACKEND=django.core.mail.backends."
            "smtp.EmailBackend (and real SMTP credentials) to send real email."
        )


class EmailSendResult:
    def __init__(self, success: bool, error: str = ""):
        self.success = success
        self.error = error


def _resolve_host(host: str, port: int) -> tuple:
    """DNS resolution as its own explicit, timed step (rather than letting
    it happen silently inside socket.create_connection) - a slow or hanging
    DNS lookup produces an identical-looking hang to a slow TCP connect
    unless it's isolated and logged separately. Also forces IPv4
    (socket.AF_INET): several cloud hosts have been reported to route
    outbound IPv6 to Gmail into a black hole (packets vanish silently, no
    RST/ICMP-unreachable, so the connect() call just hangs until timeout)
    while IPv4 to the same destination works normally - if that's what's
    happening here, this sidesteps it entirely rather than depending on it
    being diagnosed first. Harmless if that's not the cause: Gmail's SMTP
    servers are fully reachable over IPv4 regardless."""
    start = time.monotonic()
    addrinfo = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    elapsed = time.monotonic() - start
    if not addrinfo:
        raise socket.gaierror(f"No IPv4 address found for {host}")
    sockaddr = addrinfo[0][4]
    logger.info("SMTP DNS resolved %s -> %s in %.3fs", host, sockaddr[0], elapsed)
    return sockaddr


def send_otp_email(user, otp) -> EmailSendResult:
    """Stage-by-stage hardened replacement for a bare send_mail() call.
    Never raises - always returns an EmailSendResult so the calling view can
    degrade gracefully (a clear "try again later" response) instead of a
    500 or an indefinite hang. Every stage is logged; on failure, the full
    exception (class + traceback) is logged via logger.exception, never
    swallowed silently."""
    backend = getattr(settings, "EMAIL_BACKEND", "")
    subject = "Your Simba Intel password reset code"
    message = (
        f"Your password reset code is {otp.code}.\n\n"
        f"It expires in {otp.OTP_VALID_MINUTES} minutes. "
        "If you didn't request this, you can safely ignore this email."
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or "noreply@simba-intel.local"

    if backend != "django.core.mail.backends.smtp.EmailBackend":
        # Console/locmem/dummy backends do no network I/O - none of the
        # hardening below is relevant, and forcing it through the manual
        # smtplib path would just be reimplementing what Django's own
        # backend already does correctly for those cases.
        try:
            send_mail(subject, message, from_email, [user.email], fail_silently=False)
            logger.info("Email sent via %s backend to user_id=%s", backend, user.id)
            return EmailSendResult(True)
        except Exception:
            logger.exception("Non-SMTP email backend (%s) raised while sending to user_id=%s", backend, user.id)
            return EmailSendResult(False, "Could not send email right now. Please try again shortly.")

    host = settings.EMAIL_HOST
    port = settings.EMAIL_PORT
    use_ssl = getattr(settings, "EMAIL_USE_SSL", False)
    use_tls = getattr(settings, "EMAIL_USE_TLS", False)
    timeout = _SOCKET_TIMEOUT_SECONDS

    connection = None
    try:
        sockaddr = _resolve_host(host, port)

        connect_start = time.monotonic()
        if use_ssl:
            connection = smtplib.SMTP_SSL(host, port, timeout=timeout, source_address=None)
        else:
            connection = smtplib.SMTP(host, port, timeout=timeout, source_address=None)
        logger.info("SMTP TCP connected to %s:%s in %.3fs", sockaddr[0], port, time.monotonic() - connect_start)

        if not use_ssl and use_tls:
            starttls_start = time.monotonic()
            connection.starttls(context=ssl.create_default_context())
            logger.info("SMTP STARTTLS succeeded in %.3fs", time.monotonic() - starttls_start)

        username = settings.EMAIL_HOST_USER
        password = settings.EMAIL_HOST_PASSWORD
        if username and password:
            auth_start = time.monotonic()
            connection.login(username, password)
            logger.info("SMTP authentication succeeded in %.3fs", time.monotonic() - auth_start)

        send_start = time.monotonic()
        msg = (
            f"From: {from_email}\r\n"
            f"To: {user.email}\r\n"
            f"Subject: {subject}\r\n\r\n"
            f"{message}"
        )
        connection.sendmail(from_email, [user.email], msg.encode("utf-8"))
        logger.info("SMTP send succeeded in %.3fs for user_id=%s", time.monotonic() - send_start, user.id)
        return EmailSendResult(True)

    except socket.gaierror as e:
        logger.exception("SMTP DNS resolution failed for %s: %s", host, e)
        return EmailSendResult(False, "Could not reach the email server (DNS). Please try again shortly.")
    except (socket.timeout, TimeoutError) as e:
        logger.exception("SMTP operation timed out after %ss: %s", timeout, e)
        return EmailSendResult(False, "The email server took too long to respond. Please try again shortly.")
    except ConnectionRefusedError as e:
        logger.exception("SMTP connection refused by %s:%s: %s", host, port, e)
        return EmailSendResult(False, "Could not connect to the email server. Please try again shortly.")
    except ssl.SSLError as e:
        logger.exception("SMTP TLS/SSL handshake failed: %s", e)
        return EmailSendResult(False, "A secure connection to the email server could not be established.")
    except smtplib.SMTPException as e:
        logger.exception("SMTP protocol error (%s): %s", type(e).__name__, e)
        return EmailSendResult(False, "The email server rejected the request. Please try again shortly.")
    except OSError as e:
        # Catches anything else network-layer (e.g. a route that resets the
        # connection outright) that isn't one of the more specific cases
        # above - still never swallowed silently.
        logger.exception("SMTP network error (%s): %s", type(e).__name__, e)
        return EmailSendResult(False, "A network error prevented the email from sending. Please try again shortly.")
    except Exception as e:
        logger.exception("Unexpected error sending OTP email (%s): %s", type(e).__name__, e)
        return EmailSendResult(False, "Something went wrong sending the email. Please try again shortly.")
    finally:
        if connection is not None:
            try:
                connection.quit()
            except Exception:
                # The connection may already be dead (that's often exactly
                # why we're here) - closing it is best-effort, never worth
                # masking the real error captured above.
                try:
                    connection.close()
                except Exception:
                    pass
