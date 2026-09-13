from django.db import models


class Background(models.Model):
    """A character background (e.g. Soldier, Sage), sourced from db/backgrounds.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    ability_scores = models.CharField(max_length=200)
    skills = models.CharField(max_length=200)
    tools = models.CharField(max_length=200, blank=True)
    feat = models.CharField(max_length=100, blank=True)
    lore = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
