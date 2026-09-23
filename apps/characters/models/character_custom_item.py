from django.db import models


class CharacterCustomItem(models.Model):
    """An item the player made up (a keepsake, loot, a homebrew weapon) - not a catalog row.

    A separate model rather than a nullable `CharacterInventoryItem.equipment`: the catalog is
    `rules` data (read-only, wiped and reloaded by `import_rules_data`), so a custom item cannot be
    an `Equipment` row, and every consumer of `inventory_items` (derived stats, the API, the
    wizard's review) can keep assuming each one points at real catalog data. A custom item has no
    game mechanics - it takes no part in AC or attacks - so it is only ever listed, counted,
    weighed, sold or removed.

    `value` is in copper, like `Equipment.value`. `valuable` marks a trade good or valuable (gems,
    art objects), which - unlike equipment - sells for its full value, not half. `section` is the
    part of the inventory it is listed under. `type_label` is a free-text finer type within that
    section (e.g. "Light Armor", "Potion") - a label only, purely for the item's own detail line;
    it carries no rules, unlike a catalog item's real `EquipmentType`.
    """

    SECTION_CHOICES = [
        ("weapons", "Weapons"),
        ("armor", "Armor"),
        ("tools", "Tools"),
        ("misc", "Misc Items"),
    ]

    character = models.ForeignKey(
        "characters.Character", related_name="custom_items", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    quantity = models.PositiveSmallIntegerField(default=1)
    weight = models.FloatField(null=True, blank=True)
    value = models.PositiveIntegerField(null=True, blank=True)
    valuable = models.BooleanField(default=False)
    section = models.CharField(max_length=10, choices=SECTION_CHOICES, default="misc")
    type_label = models.CharField(max_length=60, blank=True, default="")
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["character", "name"]

    def __str__(self) -> str:
        return f"{self.character}: {self.name} x{self.quantity}"
