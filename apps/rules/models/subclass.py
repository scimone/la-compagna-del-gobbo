from django.db import models


class Subclass(models.Model):
    """A subclass/archetype of a Class. TODO: define fields."""

    def __str__(self) -> str:
        return f"Subclass #{self.pk}"
