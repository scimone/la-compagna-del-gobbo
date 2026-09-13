from django.db import models


class Sense(models.Model):
    """A special sense (e.g. Darkvision). TODO: define fields."""

    def __str__(self) -> str:
        return f"Sense #{self.pk}"
