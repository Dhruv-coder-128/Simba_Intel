"""Standalone SMTP connectivity test - proves, rather than assumes, exactly
which stage fails when the answer isn't in Django's own request/response
cycle (e.g. the process gets SIGKILLed before it can log anything). Uses
the EXACT same settings Django itself would use (same host/port/TLS/SSL/
credentials/timeout), so a pass/fail here is a pass/fail for the real app.

Run this directly on Render (via its shell / a one-off job) - that's the
only way to get an authoritative answer about Render's own outbound network
path to Gmail, which cannot be determined by reading code or testing
locally. Usage:

    python manage.py test_smtp_connection
    python manage.py test_smtp_connection --to someone@example.com  # sends a real test email

Prints one line per stage (DNS / TCP / STARTTLS / AUTH / SEND) as it
completes, and stops at the first stage that fails, with the exact
exception class and message - never a guess about which stage it was.
"""
import smtplib
import socket
import ssl
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Standalone SMTP connectivity test using this project's actual email settings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to", default=None,
            help="If given, actually sends a test email to this address after a successful login.",
        )

    def handle(self, *args, **options):
        host = settings.EMAIL_HOST
        port = settings.EMAIL_PORT
        use_ssl = getattr(settings, "EMAIL_USE_SSL", False)
        use_tls = getattr(settings, "EMAIL_USE_TLS", False)
        timeout = getattr(settings, "EMAIL_TIMEOUT", 10) or 10
        username = settings.EMAIL_HOST_USER
        password = settings.EMAIL_HOST_PASSWORD
        to_addr = options.get("to")

        self.stdout.write(self.style.MIGRATE_HEADING("SMTP connectivity test"))
        self.stdout.write(
            f"backend={settings.EMAIL_BACKEND} host={host} port={port} "
            f"use_tls={use_tls} use_ssl={use_ssl} timeout={timeout}s "
            f"host_user_set={bool(username)}\n"
        )

        if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
            self.stdout.write(self.style.WARNING(
                f"EMAIL_BACKEND is '{settings.EMAIL_BACKEND}', not the SMTP backend - "
                "there is no real network connection for this test to make. Set "
                "EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend to test the "
                "actual production path."
            ))
            return

        # --- Stage 1: DNS ---
        try:
            start = time.monotonic()
            addrinfo = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            elapsed = time.monotonic() - start
            sockaddr = addrinfo[0][4]
            self.stdout.write(self.style.SUCCESS(f"[1/5] DNS      OK   {host} -> {sockaddr[0]} ({elapsed:.3f}s)"))
        except socket.gaierror as e:
            self._fail("DNS", e, "Could not resolve the SMTP host at all - this points at a DNS/network "
                                  "outage on this machine, not at Gmail or credentials.")
            return
        except Exception as e:
            self._fail("DNS", e)
            return

        # --- Stage 2: TCP connect (+ implicit TLS if EMAIL_USE_SSL) ---
        connection = None
        try:
            start = time.monotonic()
            if use_ssl:
                connection = smtplib.SMTP_SSL(host, port, timeout=timeout)
            else:
                connection = smtplib.SMTP(host, port, timeout=timeout)
            elapsed = time.monotonic() - start
            self.stdout.write(self.style.SUCCESS(f"[2/5] TCP      OK   connected in {elapsed:.3f}s"))
        except socket.timeout:
            self._fail(
                "TCP connect", TimeoutError(f"timed out after {timeout}s"),
                "The TCP handshake itself never completed. This is the classic signature of an "
                "outbound firewall/network policy silently dropping the connection (no RST, no "
                "ICMP unreachable - the packets just vanish) rather than a Gmail or credentials "
                "problem. Common cause on cloud hosts: the resolved address was tried over IPv6 "
                "and that route is black-holed even though IPv4 works fine - this test forces "
                "IPv4 already, so if THIS still times out, the block is more fundamental (the "
                "whole port/host is unreachable from this network, not just over IPv6)."
            )
            return
        except (ConnectionRefusedError, OSError) as e:
            self._fail("TCP connect", e, "The connection was actively refused/reset rather than "
                                          "hanging - this is a firewall or the SMTP server itself "
                                          "rejecting the connection, not a silent network block.")
            return

        try:
            # --- Stage 3: STARTTLS ---
            if not use_ssl and use_tls:
                start = time.monotonic()
                connection.starttls(context=ssl.create_default_context())
                elapsed = time.monotonic() - start
                self.stdout.write(self.style.SUCCESS(f"[3/5] STARTTLS OK   ({elapsed:.3f}s)"))
            else:
                self.stdout.write(self.style.WARNING("[3/5] STARTTLS SKIPPED (use_tls is False or use_ssl is True)"))

            # --- Stage 4: AUTH ---
            if username and password:
                start = time.monotonic()
                connection.login(username, password)
                elapsed = time.monotonic() - start
                self.stdout.write(self.style.SUCCESS(f"[4/5] AUTH     OK   ({elapsed:.3f}s)"))
            else:
                self.stdout.write(self.style.WARNING("[4/5] AUTH     SKIPPED (EMAIL_HOST_USER/PASSWORD not set)"))
                self.stdout.write(self.style.SUCCESS(
                    "\nDNS, TCP, and STARTTLS all succeeded - the network path to the SMTP "
                    "server is fine. Set EMAIL_HOST_USER/EMAIL_HOST_PASSWORD to test AUTH."
                ))
                return

            # --- Stage 5: SEND (only if --to was given) ---
            if to_addr:
                start = time.monotonic()
                from_addr = settings.DEFAULT_FROM_EMAIL or username
                msg = (
                    f"From: {from_addr}\r\nTo: {to_addr}\r\nSubject: SIMBA_INTEL SMTP test\r\n\r\n"
                    "This is a standalone SMTP connectivity test - see chat/management/commands/"
                    "test_smtp_connection.py."
                )
                connection.sendmail(from_addr, [to_addr], msg.encode("utf-8"))
                elapsed = time.monotonic() - start
                self.stdout.write(self.style.SUCCESS(f"[5/5] SEND     OK   sent to {to_addr} ({elapsed:.3f}s)"))
            else:
                self.stdout.write(self.style.WARNING("[5/5] SEND     SKIPPED (pass --to you@example.com to send a real test email)"))

            self.stdout.write(self.style.SUCCESS("\nAll stages reached succeeded - SMTP is fully reachable from here."))

        except smtplib.SMTPAuthenticationError as e:
            self._fail("AUTH", e, "Credentials were rejected - this IS a real username/password "
                                   "problem (for Gmail: check the account uses an App Password, "
                                   "not the regular account password).")
        except smtplib.SMTPException as e:
            self._fail("SMTP protocol", e)
        except ssl.SSLError as e:
            self._fail("STARTTLS/TLS", e)
        except (socket.timeout, TimeoutError) as e:
            self._fail("post-connect operation", e, "Connected fine, but a later step "
                                                      "(STARTTLS/AUTH/SEND) hung and timed out.")
        except OSError as e:
            self._fail("post-connect operation", e)
        finally:
            try:
                connection.quit()
            except Exception:
                try:
                    connection.close()
                except Exception:
                    pass

    def _fail(self, stage, exc, note=""):
        self.stdout.write(self.style.ERROR(f"\n[FAIL] {stage}: {type(exc).__name__}: {exc}"))
        if note:
            self.stdout.write(self.style.WARNING(note))
        sys.exit(1)
