from django.db import models


class Class(models.Model):
    """A character class (e.g. Fighter, Wizard). TODO: define fields."""

    def __str__(self) -> str:
        return f"Class #{self.pk}"
