from django.db import models


class ChoiceDefinition(models.Model):
    """A choice a player must make (e.g. pick 2 skills). TODO: define fields."""

    def __str__(self) -> str:
        return f"ChoiceDefinition #{self.pk}"
