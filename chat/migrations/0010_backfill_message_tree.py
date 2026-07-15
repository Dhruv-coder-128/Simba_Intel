from django.db import migrations


def backfill_messages(apps, schema_editor):
    """Reproduce today's linear ChatMessage history as a single branch (no
    siblings) in the new Message tree. ChatMessage rows are never touched or
    deleted - this is a pure additive backfill, safe to re-run only once
    (guarded by session.active_leaf already being set)."""
    ChatSession = apps.get_model('chat', 'ChatSession')
    ChatMessage = apps.get_model('chat', 'ChatMessage')
    Message = apps.get_model('chat', 'Message')

    for session in ChatSession.objects.all().iterator():
        if session.active_leaf_id is not None:
            continue  # already migrated

        parent = None
        chat_messages = ChatMessage.objects.filter(session=session).order_by('timestamp')
        for cm in chat_messages:
            user_msg = Message.objects.create(
                session=session,
                role='user',
                content=cm.user_query or '',
                parent=parent,
            )
            Message.objects.filter(pk=user_msg.pk).update(created_at=cm.timestamp)

            assistant_msg = Message.objects.create(
                session=session,
                role='assistant',
                content=cm.ai_response or '',
                parent=user_msg,
                extra_data=cm.extra_data,
                latency=cm.latency,
            )
            Message.objects.filter(pk=assistant_msg.pk).update(created_at=cm.timestamp)

            parent = assistant_msg

        if parent is not None:
            session.active_leaf = parent
            session.save(update_fields=['active_leaf'])


def unbackfill_messages(apps, schema_editor):
    """Reverse: drop the generated Message tree and clear active_leaf.
    ChatMessage (the source of truth for this operation) is untouched, so
    re-running the forward migration reproduces the same tree."""
    ChatSession = apps.get_model('chat', 'ChatSession')
    Message = apps.get_model('chat', 'Message')

    ChatSession.objects.update(active_leaf=None)
    Message.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_message_chatsession_active_leaf_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_messages, unbackfill_messages),
    ]
