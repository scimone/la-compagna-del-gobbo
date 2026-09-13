from django.db import models


class Equipment(models.Model):
    """An item of equipment (weapon, armor, gear, tool, ...), sourced from db/equipments.json.

    Tools, instruments and gaming sets are not split into a separate catalog: in the source data
    they are just Equipment rows with `category` set to "Tool", "Artisan's Tools", "Instrument" or
    "Gaming Set" (see the `rules.Tool` placeholder).
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    category = models.CharField(max_length=50)
    weapon_category = models.CharField(max_length=20, blank=True)
    weight = models.CharField(max_length=30, blank=True)
    value = models.CharField(max_length=30, blank=True)
    damage = models.CharField(max_length=50, blank=True)
    ac = models.CharField(max_length=10, blank=True)
    range = models.CharField(max_length=50, blank=True)
    attunement = models.CharField(max_length=100, blank=True)
    properties = models.CharField(max_length=200, blank=True)
    property_refs = models.JSONField(default=list, blank=True)
    mastery = models.CharField(max_length=50, blank=True)
    mastery_refs = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
