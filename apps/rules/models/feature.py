from django.db import models


class Feature(models.Model):
    """A discrete class/subclass/species/feat feature grant. TODO: define fields."""

    def __str__(self) -> str:
        return f"Feature #{self.pk}"
