from django.db import models


class Effect(models.Model):
    """A mechanical effect attached to a Feature. TODO: define fields."""

    def __str__(self) -> str:
        return f"Effect #{self.pk}"
