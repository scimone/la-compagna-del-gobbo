from django.db import models


class ClassLevel(models.Model):
    """The per-level progression row for a Class. TODO: define fields."""

    def __str__(self) -> str:
        return f"ClassLevel #{self.pk}"
