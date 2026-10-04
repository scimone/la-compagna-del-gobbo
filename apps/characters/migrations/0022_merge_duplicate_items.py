from django.db import migrations


def merge(apps, schema_editor):
    Item = apps.get_model("characters", "CharacterInventoryItem")
    groups = {}
    for row in Item.objects.order_by("pk"):
        groups.setdefault((row.character_id, row.equipment_id, row.parent_id), []).append(row)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        keep = rows[0]
        keep.quantity = min(sum(r.quantity for r in rows), 32767)
        keep.equipped = any(r.equipped for r in rows)
        keep.attuned = any(r.attuned for r in rows)
        keep.notes = next((r.notes for r in rows if r.notes), "")
        keep.save()
        Item.objects.filter(pk__in=[r.pk for r in rows[1:]]).delete()


class Migration(migrations.Migration):
    dependencies = [("characters", "0021_conditions")]
    operations = [migrations.RunPython(merge, migrations.RunPython.noop)]
