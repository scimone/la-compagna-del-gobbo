from django.db import models


class Rule(models.Model):
    """A named rule/keyword definition (e.g. Grappling, Cover). TODO: define fields."""

    def __str__(self) -> str:
        return f"Rule #{self.pk}"
