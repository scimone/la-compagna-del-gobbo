from django.db import models


class CharacterSense(models.Model):
    """A sense granted to a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterSense #{self.pk}"
