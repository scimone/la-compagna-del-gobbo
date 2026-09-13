from django.db import models


class Skill(models.Model):
    """A skill (e.g. Athletics, Perception). TODO: define fields."""

    def __str__(self) -> str:
        return f"Skill #{self.pk}"
