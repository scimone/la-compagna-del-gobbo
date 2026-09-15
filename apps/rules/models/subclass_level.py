from django.db import models


class SubclassLevel(models.Model):
    """The per-level progression row for a Subclass, sourced from db/classes.json subclass
    `features` (grouped by level: a couple of subclasses grant more than one feature at the
    same level, e.g. Bard's College of Dance at level 6).

    Does *not* store the level's features itself (no `features` JSON field) - those live only as
    `Feature` rows FK'd back via `feature_rows` (`feature.subclass_level.level == self.level` by
    construction). Unlike `Class.features`/`Species.entries`/`Feat.entries` - each already the
    source's own natural field, kept verbatim alongside the `Feature` rows derived from it - this
    model exists purely as a grouping of `Feature` rows, so a second copy of the same data as a
    JSON blob here would be pure duplication with no independent reason to exist. See the
    "Known data-import issues" section of the README.
    """

    subclass = models.ForeignKey("rules.Subclass", related_name="levels", on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["subclass", "level"]
        constraints = [
            models.UniqueConstraint(fields=["subclass", "level"], name="unique_subclass_level"),
        ]

    def __str__(self) -> str:
        return f"{self.subclass} {self.level}"
