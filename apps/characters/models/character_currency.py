from django.db import models


class CharacterCurrency(models.Model):
    """The coin purse of a Character. TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterCurrency #{self.pk}"
