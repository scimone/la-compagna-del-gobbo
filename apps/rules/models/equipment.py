from django.db import models


class Equipment(models.Model):
    """An item of equipment (weapon, armor, gear). TODO: define fields."""

    def __str__(self) -> str:
        return f"Equipment #{self.pk}"
