from django.db import models


class Subclass(models.Model):
    """A subclass/archetype of a Class, sourced from db/classes.json `subclasses` (XPHB only).

    The source doesn't give subclasses their own id/page/srd fields (only a name, image and
    features list), so those aren't modeled here. Per-level feature grants live on
    `SubclassLevel`.

    `description` is the subclass's own flavor text - see the data-cleanup note in
    `apps/rules/management/commands/import_rules_data.py` (`_import_classes`) for why this is a
    separate field rather than living on the granting `SubclassLevel`/`Feature` row: the source
    bundles it together with that level's real named features under one block titled after the
    subclass itself, which isn't a feature at all and was previously imported as if it were one.
    """

    klass = models.ForeignKey("rules.Class", related_name="subclasses", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["klass", "name"]
        constraints = [
            models.UniqueConstraint(fields=["klass", "name"], name="unique_class_subclass"),
        ]

    def __str__(self) -> str:
        return f"{self.klass.name}: {self.name}"
