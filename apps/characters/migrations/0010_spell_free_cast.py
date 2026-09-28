from django.db import migrations, models


def mark_feat_spells(apps, schema_editor):
    """The level 1 spell a feat grants (always prepared, from a `feat:` source) is the one that can
    be cast once for free."""
    CharacterSpell = apps.get_model("characters", "CharacterSpell")
    CharacterSpell.objects.filter(source__startswith="feat:", always_prepared=True).update(
        free_cast=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("characters", "0009_feature_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="characterspell",
            name="free_cast",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="characterspell",
            name="free_cast_used",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_feat_spells, migrations.RunPython.noop),
    ]
