from django.db import models


class Mastery(models.Model):
    """A weapon mastery property. TODO: define fields."""

    def __str__(self) -> str:
        return f"Mastery #{self.pk}"
