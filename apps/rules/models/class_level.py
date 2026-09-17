from django.db import models


class ClassLevel(models.Model):
    """The per-level progression row for a Class, sourced from `db/classes.json`'s per-class
    `classTableGroups`/spellcasting-progression fields.

    `spell_slots`/`cantrips_known`/`spells_known_or_prepared` are split out as real fields now
    that the source gives them as structured per-level progressions
    (`classTableGroups[].rowsSpellProgression`, `cantripProgression`,
    `preparedSpellsProgression`/`spellsKnownProgressionFixed(ByLevel)`) instead of only baking them
    into opaque table-row strings. `columns` remains a verbatim `{header: value}` mapping for
    whatever's left (e.g. Barbarian's Rages/Rage Damage, Monk's Martial Arts die/Unarmored
    Movement) - these stay per-class and typed-per-cell (`{"type": "dice", ...}`, `{"type":
    "bonus", "value": N}`) rather than flattened to a display string, so no information is lost
    even though they aren't split into their own dedicated columns - that's a bigger project than
    this pass needs.

    Doesn't store the level's feature text itself - that lives only as `Feature` rows FK'd back
    via `feature_rows` (`feature.class_level.level == self.level` by construction), the same
    relationship `SubclassLevel` uses for subclass features. Not every level has one (e.g. most
    classes grant nothing new at level 19).
    """

    klass = models.ForeignKey("rules.Class", related_name="levels", on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField()
    spell_slots = models.JSONField(default=list, blank=True)
    cantrips_known = models.PositiveSmallIntegerField(null=True, blank=True)
    spells_known_or_prepared = models.PositiveSmallIntegerField(null=True, blank=True)
    columns = models.JSONField(default=dict)

    class Meta:
        ordering = ["klass", "level"]
        constraints = [
            models.UniqueConstraint(fields=["klass", "level"], name="unique_class_level"),
        ]

    def __str__(self) -> str:
        return f"{self.klass.name} {self.level}"
