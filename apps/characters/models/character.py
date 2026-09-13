from django.db import models


class Character(models.Model):
    """A player character. TODO: define fields."""

    def __str__(self) -> str:
        return f"Character #{self.pk}"
