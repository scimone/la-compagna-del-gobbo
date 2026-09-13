from django.db import models


class CharacterResource(models.Model):
    """A limited-use resource of a Character (e.g. Rage). TODO: define fields."""

    def __str__(self) -> str:
        return f"CharacterResource #{self.pk}"
