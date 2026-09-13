from django.db import models


class Spell(models.Model):
    """A spell definition. TODO: define fields."""

    def __str__(self) -> str:
        return f"Spell #{self.pk}"
