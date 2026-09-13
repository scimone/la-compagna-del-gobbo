from django.db import models


class EquipmentProperty(models.Model):
    """A property attached to Equipment (e.g. Finesse). TODO: define fields."""

    def __str__(self) -> str:
        return f"EquipmentProperty #{self.pk}"
