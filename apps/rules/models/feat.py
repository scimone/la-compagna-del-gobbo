from django.db import models


class Feat(models.Model):
    """A feat (e.g. Alert, Tough). TODO: define fields."""

    def __str__(self) -> str:
        return f"Feat #{self.pk}"
