from django.db import models


class EquipmentProperty(models.Model):
    """A property attached to Equipment (e.g. Finesse).

    Sourced from db/equipment_properties.json.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    abbreviation = models.CharField(max_length=10)
    hidden = models.BooleanField(default=False)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
