import json

from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def backfill_additional_spells(apps, schema_editor):
    # Fill the new column on the rows already loaded, without a full `import_rules_data` reload.
    OptionalFeature = apps.get_model("rules", "OptionalFeature")
    path = settings.BASE_DIR / "db" / "optionalfeatures.json"
    if not OptionalFeature.objects.exists() or not path.exists():
        return
    for raw in json.loads(path.read_text(encoding="utf-8"))["optionalfeature"]:
        if raw.get("additionalSpells"):
            OptionalFeature.objects.filter(pk=slugify(raw["name"])).update(
                additional_spells=raw["additionalSpells"]
            )


class Migration(migrations.Migration):
    dependencies = [("rules", "0022_condition")]

    operations = [
        migrations.AddField(
            model_name="optionalfeature",
            name="additional_spells",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_additional_spells, migrations.RunPython.noop),
    ]
