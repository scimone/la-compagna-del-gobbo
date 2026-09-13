from django.db import models


class Subclass(models.Model):
    """A subclass/archetype of a Class, sourced from db/classes.json `subclasses` (XPHB only).

    The source doesn't give subclasses their own id/page/srd fields (only a name, image and
    features list), so those aren't modeled here. Per-level feature grants live on
    `SubclassLevel`.
    """

    klass = models.ForeignKey("rules.Class", related_name="subclasses", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["klass", "name"]
        constraints = [
            models.UniqueConstraint(fields=["klass", "name"], name="unique_class_subclass"),
        ]

    def __str__(self) -> str:
        return f"{self.klass.name}: {self.name}"
