from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Log = apps.get_model("ai", "AIRequestLog")
    for entry in Log.objects.exclude(user=None).select_related("user"):
        entry.display_name = (entry.user.first_name or "").strip() or entry.username
        entry.save(update_fields=["display_name"])
    Log.objects.filter(display_name="").update(display_name=F("username"))


class Migration(migrations.Migration):
    dependencies = [("ai", "0004_chat_activity_and_display_name")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
