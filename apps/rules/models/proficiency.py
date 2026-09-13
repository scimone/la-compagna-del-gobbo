from django.db import models


class Proficiency(models.Model):
    """A proficiency category (weapon/armor/save/etc.). TODO: define fields."""

    def __str__(self) -> str:
        return f"Proficiency #{self.pk}"
