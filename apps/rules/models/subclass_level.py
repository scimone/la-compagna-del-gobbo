from django.db import models


class SubclassLevel(models.Model):
    """The per-level progression row for a Subclass, sourced from db/classes.json subclass
    `features` (grouped by level: a couple of subclasses grant more than one feature at the
    same level, e.g. Bard's College of Dance at level 6).
    """

    subclass = models.ForeignKey("rules.Subclass", related_name="levels", on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField()
    features = models.JSONField(default=list)

    class Meta:
        ordering = ["subclass", "level"]
        constraints = [
            models.UniqueConstraint(fields=["subclass", "level"], name="unique_subclass_level"),
        ]

    def __str__(self) -> str:
        return f"{self.subclass} {self.level}"
