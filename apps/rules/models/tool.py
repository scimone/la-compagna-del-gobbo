from django.db import models


class Tool(models.Model):
    """A tool (e.g. Thieves' Tools, Herbalism Kit). TODO: define fields."""

    def __str__(self) -> str:
        return f"Tool #{self.pk}"
