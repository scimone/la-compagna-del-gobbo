from django.db import migrations


def drop(apps, schema_editor):
    # In the 2024 rules Divine Sense is a Channel Divinity effect, not a counter of its own.
    apps.get_model("characters", "CharacterResource").objects.filter(name="Divine Sense").delete()


class Migration(migrations.Migration):
    dependencies = [("characters", "0033_created_slots_use_flags")]
    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
