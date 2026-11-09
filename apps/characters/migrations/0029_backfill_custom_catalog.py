from django.db import migrations

FIELDS = [
    "name", "weight", "value", "valuable", "section", "type_label", "weapon_category",
    "description", "armor_kind", "ac", "strength_requirement", "stealth_disadvantage",
    "damage_dice", "damage_type", "versatile_damage_dice", "ranged", "range", "finesse",
    "two_handed", "wearable", "effects",
]  # fmt: skip


def backfill(apps, schema_editor):
    """Every custom item that already exists becomes a catalog entry of its character's campaign
    (the newest one wins when several share a name)."""
    Item = apps.get_model("characters", "CharacterCustomItem")
    Entry = apps.get_model("characters", "CustomCatalogItem")
    seen = set()
    for item in Item.objects.select_related("character").order_by("-pk"):
        key = (item.character.campaign_id, item.name.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        Entry.objects.create(
            campaign_id=item.character.campaign_id, **{f: getattr(item, f) for f in FIELDS}
        )


class Migration(migrations.Migration):
    dependencies = [("characters", "0028_custom_catalog_item")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
