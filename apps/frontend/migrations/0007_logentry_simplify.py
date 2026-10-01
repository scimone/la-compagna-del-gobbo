from django.db import migrations, models
import django.db.models.deletion

OLD_FIELDS = [
    ("location", "Visited locations"),
    ("characters_met", "Characters met"),
    ("fights", "Fights"),
    ("objectives", "Objectives"),
    ("insights", "Insights"),
    ("notes", "Other notes"),
]


def merge_fields(apps, schema_editor):
    """The six old free-text fields become one text, each under its old label."""
    LogEntry = apps.get_model("frontend", "LogEntry")
    for entry in LogEntry.objects.all():
        parts = [
            f"{label}:\n{getattr(entry, name).strip()}"
            for name, label in OLD_FIELDS
            if getattr(entry, name).strip()
        ]
        entry.text = "\n\n".join(parts)
        entry.save(update_fields=["text"])


class Migration(migrations.Migration):

    dependencies = [
        ("characters", "0011_character_picture"),
        ("frontend", "0006_logentry_location_text"),
    ]

    operations = [
        migrations.AddField(
            model_name="logentry",
            name="kind",
            field=models.CharField(
                choices=[("objective", "Objective"), ("personal", "Personal")],
                default="objective",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="logentry",
            name="character",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="log_entries",
                to="characters.character",
            ),
        ),
        migrations.AddField(
            model_name="logentry",
            name="text",
            field=models.TextField(blank=True),
        ),
        migrations.RunPython(merge_fields, migrations.RunPython.noop),
        migrations.RemoveField(model_name="logentry", name="location"),
        migrations.RemoveField(model_name="logentry", name="characters_met"),
        migrations.RemoveField(model_name="logentry", name="fights"),
        migrations.RemoveField(model_name="logentry", name="objectives"),
        migrations.RemoveField(model_name="logentry", name="insights"),
        migrations.RemoveField(model_name="logentry", name="notes"),
    ]
