from django.db import models


class CharacterProficiency(models.Model):
    """A proficiency granted to a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterProficiency #{self.pk}"
