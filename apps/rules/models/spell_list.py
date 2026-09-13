from django.db import models


class SpellList(models.Model):
    """The list of spells available to a given Class. TODO: define fields."""

    def __str__(self) -> str:
        return f"SpellList #{self.pk}"
