from django.db import models


class CharacterClass(models.Model):
    """A class/subclass a Character has levels in. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterClass #{self.pk}"
