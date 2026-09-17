from django.db import models


class EquipmentType(models.Model):
    """A category of Equipment (e.g. "Melee Weapon", "Heavy Armor"), sourced from
    `db/equipment-base.json`'s `itemType` (23 rows).

    Wholly new: the old format had no such catalog, only a free-text `Equipment.category` field
    ("Melee Weapon" as a bare string). The new source gives every `baseitem`/`item` a `type`
    reference (`"M|XPHB"`) resolving to one of these rows by `abbreviation`, making this the
    cleanest new FK opportunity in the equipment domain.
    """

    id = models.SlugField(primary_key=True, max_length=50)
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=10)
    page = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
