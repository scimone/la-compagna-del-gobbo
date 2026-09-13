from django.db import models


class CharacterFeature(models.Model):
    """A Feature granted to a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterFeature #{self.pk}"
