from django.db import models


class CustomItemBase(models.Model):
    """The fields of an item the player made up: shared by the item on a sheet
    (`CharacterCustomItem`) and its entry in the campaign's permanent catalog (`CustomCatalogItem`).

    An item the player made up (a keepsake, loot, a homebrew weapon) - not a catalog row.

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
    it carries no rules, unlike a catalog item's real `EquipmentType`. `weapon_category` is the
    same idea for a weapon's Simple/Martial split - only ever shown, like `type_label`, never
    checked against a proficiency in the proficiencies list (`_weapon_groups()`).

    A custom item *can* be worn, though, once it carries stats: armor with an `armor_kind` and `ac`
    counts for Armor Class (`derived_stats`), a weapon with `damage_dice` is an attack (its
    `weapon_category` decides the proficiency). `damage_type` is one of the catalog's own words
    (`slashing`, `piercing`, `bludgeoning`). `equipped` is the "worn / wielded" flag.
    """

    SECTION_CHOICES = [
        ("weapons", "Weapons"),
        ("armor", "Armor"),
        ("tools", "Tools"),
        ("misc", "Misc Items"),
    ]
    WEAPON_CATEGORY_CHOICES = [
        ("simple", "Simple"),
        ("martial", "Martial"),
    ]

    ARMOR_KIND_CHOICES = [
        ("light", "Light"),
        ("medium", "Medium"),
        ("heavy", "Heavy"),
        ("shield", "Shield"),
    ]

    name = models.CharField(max_length=200)
    weight = models.FloatField(null=True, blank=True)
    value = models.PositiveIntegerField(null=True, blank=True)
    valuable = models.BooleanField(default=False)
    section = models.CharField(max_length=10, choices=SECTION_CHOICES, default="misc")
    type_label = models.CharField(max_length=60, blank=True, default="")
    weapon_category = models.CharField(
        max_length=10, choices=WEAPON_CATEGORY_CHOICES, blank=True, default=""
    )
    description = models.TextField(blank=True, default="")
    # What lets a custom weapon/armor/shield be worn: the same few numbers a catalog row has. All
    # optional - an item without them stays a plain, unwearable keepsake.
    armor_kind = models.CharField(max_length=10, choices=ARMOR_KIND_CHOICES, blank=True, default="")
    ac = models.PositiveSmallIntegerField(null=True, blank=True)
    strength_requirement = models.PositiveSmallIntegerField(null=True, blank=True)
    stealth_disadvantage = models.BooleanField(default=False)
    damage_dice = models.CharField(max_length=20, blank=True, default="")
    damage_type = models.CharField(max_length=20, blank=True, default="")
    versatile_damage_dice = models.CharField(max_length=20, blank=True, default="")
    ranged = models.BooleanField(default=False)
    #: A ranged weapon's range in feet, as the catalog writes it: `"80/320"`.
    range = models.CharField(max_length=20, blank=True, default="")
    finesse = models.BooleanField(default=False)
    two_handed = models.BooleanField(default=False)
    #: Worn like gear without being a weapon or armor (a ring, a cloak): such an item has no stats
    #: of its own, only `effects` - see `characters.custom_effects` for their shape.
    wearable = models.BooleanField(default=False)
    effects = models.JSONField(default=list, blank=True)

    class Meta:
        abstract = True


class CharacterCustomItem(CustomItemBase):
    """An item of the player's own on one character's sheet (see `CustomItemBase`)."""

    character = models.ForeignKey(
        "characters.Character", related_name="custom_items", on_delete=models.CASCADE
    )
    quantity = models.PositiveSmallIntegerField(default=1)
    equipped = models.BooleanField(default=False)

    class Meta:
        ordering = ["character", "name"]

    def __str__(self) -> str:
        return f"{self.character}: {self.name} x{self.quantity}"


class CustomCatalogItem(CustomItemBase):
    """An item a player made up once, kept for good: every custom item added to a sheet (and every
    one that already existed) is also an entry here, so the whole campaign can add it again from
    the "add an item" list without retyping it. The catalog proper is `rules` data, wiped and
    reloaded by `import_rules_data`; these belong to the campaign, so they live beside the
    characters. One entry per name within a campaign - adding the same name again refreshes it."""

    campaign = models.ForeignKey(
        "campaigns.Campaign", related_name="custom_catalog", on_delete=models.CASCADE
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.campaign}: {self.name}"
