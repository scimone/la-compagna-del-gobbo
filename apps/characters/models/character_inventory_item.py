from django.db import models


class CharacterInventoryItem(models.Model):
    """An Equipment item owned by a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterInventoryItem #{self.pk}"
