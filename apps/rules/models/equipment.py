from django.db import models


class Equipment(models.Model):
    """An item of equipment (weapon, armor, gear, tool, ...), sourced from `db/equipment-base.json`
    (`baseitem` - weapon/armor stat blocks, 94 rows) and `db/equipment.json` (`item` - everything
    else: general gear, tools, vehicles, foci, 123 rows). 94 + 123 = 217, an exact match for the
    old single flat catalog's row count - the new source partitions the same catalog differently,
    it doesn't add or drop content, so both import into this one model rather than being split
    into separate base-item/item models (matching this project's existing one-flat-table
    philosophy - see the README's `Tool`/`SpellList`-removal rationale).

    Tools, instruments and gaming sets are not split into a separate catalog: in the source data
    they are just Equipment rows whose `type` is one of those `EquipmentType` categories.

    `weight`/`value` are the source's own bare numbers now (`value` in copper, i.e. old-gp x 100) -
    no more unit suffix to carry, so no more `CharField`. `properties`/`masteries` are real M2Ms
    now that the source gives every reference as a resolvable `"name|source"` key instead of a
    free-text display string (the old `properties`/`mastery` display strings and
    `property_refs`/`mastery_refs` duplicate JSON lists are gone - the M2M *is* the reference,
    `EquipmentProperty.template`/`Mastery.entries` already carry what's needed to render it).

    `stats` is a deliberate catch-all `JSONField` for mechanical data that's real but too sparse/
    per-category to earn its own column (container capacity, vehicle crew/AC/HP/speed/cargo,
    focus-type flags, ...) - adding a dozen nullable vehicle-only columns for a handful of rows
    would be more schema than the data warrants; storing the raw sub-object loses nothing.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    type = models.ForeignKey(
        "rules.EquipmentType",
        related_name="equipment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    weapon_category = models.CharField(max_length=20, blank=True, default="")
    weight = models.FloatField(null=True, blank=True)
    value = models.PositiveIntegerField(null=True, blank=True)
    damage_dice = models.CharField(max_length=20, blank=True, default="")
    damage_type = models.CharField(max_length=20, blank=True, default="")
    versatile_damage_dice = models.CharField(max_length=20, blank=True, default="")
    ac = models.PositiveSmallIntegerField(null=True, blank=True)
    strength_requirement = models.PositiveSmallIntegerField(null=True, blank=True)
    stealth_disadvantage = models.BooleanField(default=False)
    range = models.CharField(max_length=50, blank=True, default="")
    attunement = models.CharField(max_length=100, blank=True, default="")
    properties = models.ManyToManyField(
        "rules.EquipmentProperty", related_name="equipment", blank=True
    )
    masteries = models.ManyToManyField("rules.Mastery", related_name="equipment", blank=True)
    group = models.ForeignKey(
        "rules.EquipmentGroup",
        related_name="items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    pack_contents = models.ManyToManyField(
        "self",
        through="rules.EquipmentPackContent",
        through_fields=("pack", "item"),
        symmetrical=False,
        related_name="contained_in",
        blank=True,
    )
    stats = models.JSONField(default=dict, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
