from django.db import migrations


def give_spell(apps, schema_editor):
    # Wild Companion casts Find Familiar: a Druid that has the feature gets the spell (unless it
    # already has it from somewhere else).
    Feature = apps.get_model("characters", "CharacterFeature")
    Spell = apps.get_model("characters", "CharacterSpell")
    ids = Feature.objects.filter(feature__name_en="Wild Companion").values_list(
        "character_id", flat=True
    )
    for character_id in set(ids):
        Spell.objects.get_or_create(
            character_id=character_id,
            spell_id="find-familiar",
            defaults={
                "prepared": True,
                "always_prepared": True,
                "source": "feature:wild-companion",
                "klass_id": "druid",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("characters", "0034_drop_divine_sense_counter")]
    operations = [migrations.RunPython(give_spell, migrations.RunPython.noop)]
