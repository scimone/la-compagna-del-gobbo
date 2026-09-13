from django.db import models


class CharacterSpell(models.Model):
    """A Spell known/prepared by a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterSpell #{self.pk}"
