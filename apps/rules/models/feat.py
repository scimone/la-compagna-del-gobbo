from django.db import models


class Feat(models.Model):
    """A feat (e.g. Alert, Tough), sourced from db/feats.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    category = models.CharField(max_length=30)
    prerequisite = models.CharField(max_length=200, blank=True, default="")
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
