import json

from django.conf import settings
from django.db import migrations, models
from django.utils.text import slugify


def backfill_ability(apps, schema_editor):
    # Fill the new column on the rows already loaded, without a full `import_rules_data` reload.
    Feat = apps.get_model("rules", "Feat")
    path = settings.BASE_DIR / "db" / "feats.json"
    if not Feat.objects.exists() or not path.exists():
        return
    for raw in json.loads(path.read_text(encoding="utf-8"))["feat"]:
        if raw.get("ability"):
            Feat.objects.filter(pk=slugify(raw["name"])).update(ability=raw["ability"])


class Migration(migrations.Migration):
    dependencies = [("rules", "0019_handbook_chapters")]

    operations = [
        migrations.AddField(
            model_name="feat",
            name="ability",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_ability, migrations.RunPython.noop),
    ]
