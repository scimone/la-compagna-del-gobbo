from django.db import migrations


def always_prepare(apps, schema_editor):
    """A spell added from the sheet that is on no preparing class's list can never be swapped for
    another: it is always prepared (see `play.add_spell`)."""
    CharacterSpell = apps.get_model("characters", "CharacterSpell")
    CharacterSpell.objects.filter(
        source="sheet", klass__isnull=True, always_prepared=False, spell__level__gt=0
    ).update(prepared=True, always_prepared=True)


class Migration(migrations.Migration):
    dependencies = [("characters", "0013_character_spell_changes")]

    operations = [migrations.RunPython(always_prepare, migrations.RunPython.noop)]
