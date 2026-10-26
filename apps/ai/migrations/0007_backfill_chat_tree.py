from django.db import migrations


def chain(apps, schema_editor):
    """Chats used to be a flat list: each message now follows the one before it, and the last
    one is the thread's head."""
    Thread = apps.get_model("ai", "ChatThread")
    for thread in Thread.objects.all():
        previous = None
        for message in thread.messages.order_by("created_at", "pk"):
            message.parent = previous
            message.save(update_fields=["parent"])
            previous = message
        thread.head = previous
        thread.save(update_fields=["head"])


class Migration(migrations.Migration):
    dependencies = [("ai", "0006_chat_versions")]
    operations = [migrations.RunPython(chain, migrations.RunPython.noop)]
