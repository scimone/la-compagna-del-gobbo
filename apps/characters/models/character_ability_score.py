from django.db import models


class CharacterAbilityScore(models.Model):
    """One ability score for a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterAbilityScore #{self.pk}"
