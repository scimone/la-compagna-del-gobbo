from django.db import models


class Background(models.Model):
    """A character background (e.g. Soldier, Sage). TODO: define fields."""

    def __str__(self) -> str:
        return f"Background #{self.pk}"
