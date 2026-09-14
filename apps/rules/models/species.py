from django.db import models


class Species(models.Model):
    """A player species (e.g. Elf, Dwarf), sourced from db/species.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=150, blank=True, default="")
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    size = models.CharField(max_length=50)
    speed = models.CharField(max_length=30)
    walk_speed = models.PositiveSmallIntegerField(default=0)
    fly_speed = models.PositiveSmallIntegerField(default=0)
    swim_speed = models.PositiveSmallIntegerField(default=0)
    climb_speed = models.PositiveSmallIntegerField(default=0)
    creature_type = models.CharField(max_length=50)
    parent_race = models.CharField(max_length=100, blank=True, default="")
    lore = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
