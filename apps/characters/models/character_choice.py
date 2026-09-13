from django.db import models


class CharacterChoice(models.Model):
    """A resolved ChoiceDefinition selection for a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterChoice #{self.pk}"
