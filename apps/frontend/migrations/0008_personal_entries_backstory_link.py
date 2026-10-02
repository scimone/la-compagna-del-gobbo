from django.db import migrations

SENTENCE = "Here you can read my full backstory"


def add_link(apps, schema_editor):
    """A one-off: each personal message so far gets the sentence, as a Markdown link to its
    character's biography, so it can be edited like the rest of the text."""
    LogEntry = apps.get_model("frontend", "LogEntry")
    for entry in LogEntry.objects.filter(kind="personal", character__isnull=False):
        url = f"/characters/{entry.character_id}/?tab=biography"
        if url in entry.text:
            continue
        link = f"[{SENTENCE}]({url})."
        entry.text = f"{entry.text.rstrip()}\n\n{link}" if entry.text.strip() else link
        entry.save(update_fields=["text"])


class Migration(migrations.Migration):

    dependencies = [
        ("frontend", "0007_logentry_simplify"),
    ]

    operations = [migrations.RunPython(add_link, migrations.RunPython.noop)]
