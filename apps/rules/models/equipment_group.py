from django.db import models


class EquipmentGroup(models.Model):
    """A named category of interchangeable Equipment (e.g. "Arcane Focus", "Artisan's Tools"),
    sourced from `db/equipment.json`'s `itemGroup` (6 rows).

    Wholly new: the old format had no such grouping. Member items point back via `Equipment.group`
    (resolved from the item's own `group` field, a bare name with no source segment - unambiguous
    since there are only 6 groups). `focus_classes` links `itemGroup.focus` (a list of class
    names, e.g. Arcane Focus -> Sorcerer/Warlock/Wizard) directly to `rules.Class` - a clean FK
    the old format had no way to express at all.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField(null=True, blank=True)
    focus_classes = models.ManyToManyField(
        "rules.Class", related_name="equipment_group_foci", blank=True
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
