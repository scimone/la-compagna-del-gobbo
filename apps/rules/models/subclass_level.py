from django.db import models


class SubclassLevel(models.Model):
    """The per-level progression row for a Subclass. TODO: define fields."""

    def __str__(self) -> str:
        return f"SubclassLevel #{self.pk}"
