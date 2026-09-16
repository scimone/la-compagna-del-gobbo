from django.db import models


class ClassLevel(models.Model):
    """The per-level progression row for a Class, sourced from db/classes.json `table` rows.

    Each class's table has different columns (e.g. Barbarian has Rages/Rage Damage/Weapon
    Mastery, Wizard has Cantrips/Prepared Spells/spell-slot columns per spell level), so the row
    is kept as a verbatim {header: value} mapping in `columns` rather than a fixed set of fields.

    Doesn't store the level's feature text itself - that lives only as `Feature` rows FK'd back
    via `feature_rows` (`feature.class_level.level == self.level` by construction), the same
    relationship `SubclassLevel` already used for subclass features. Not every level has one
    (e.g. most classes grant nothing new at level 19).
    """

    klass = models.ForeignKey("rules.Class", related_name="levels", on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField()
    columns = models.JSONField(default=dict)

    class Meta:
        ordering = ["klass", "level"]
        constraints = [
            models.UniqueConstraint(fields=["klass", "level"], name="unique_class_level"),
        ]

    def __str__(self) -> str:
        return f"{self.klass.name} {self.level}"
