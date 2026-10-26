from django.db import migrations


def drop_global_settings(apps, schema_editor):
    """Settings used to be one global row; they are per campaign now and a campaign must not
    inherit another's key, so the old row (and its key) is dropped - enter it again per campaign."""
    apps.get_model("ai", "AISettings").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0001_initial")]
    operations = [migrations.RunPython(drop_global_settings, migrations.RunPython.noop)]
