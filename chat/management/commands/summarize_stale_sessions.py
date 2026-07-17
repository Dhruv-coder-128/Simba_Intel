"""Background processing (Part 8) - the batch counterpart to the inline
per-turn trigger in chat.services.conversation_memory.maybe_summarize_session
(called automatically after every ask_ai turn). That inline call keeps a
session's summary fresh as it's actively being used; this command exists for
everything the inline path can't reach: a session nobody has continued
recently but that still crossed the summarization threshold, or one created
before this feature existed. Intended to run on a schedule (e.g. an hourly
Render Cron Job) rather than in the request/response path - see this
project's "future-ready" notes for why a full task queue (Celery/RQ) isn't
introduced just for this one job.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count, F

from chat.models import ChatSession
from chat.services.conversation_memory import maybe_summarize_session, SUMMARIZE_EVERY_N_MESSAGES


class Command(BaseCommand):
    help = "Summarize every chat session that has drifted past its summarization threshold since it was last summarized."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=200,
            help="Maximum number of sessions to process in one run (default 200) - caps a single invocation's AI-call cost/runtime.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        candidates = (
            ChatSession.objects.annotate(message_count=Count("thread"))
            .filter(message_count__gte=F("summary_message_count") + SUMMARIZE_EVERY_N_MESSAGES)
            .order_by("id")[:limit]
        )

        processed = 0
        for session in candidates:
            before = session.summary_message_count
            maybe_summarize_session(session)
            session.refresh_from_db(fields=["summary_message_count"])
            if session.summary_message_count != before:
                processed += 1

        self.stdout.write(self.style.SUCCESS(
            f"Checked {len(candidates)} stale session(s), summarized {processed}."
        ))
