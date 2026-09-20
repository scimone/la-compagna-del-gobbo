from django.db import models


class Sense(models.Model):
    """A special sense (e.g. Darkvision), sourced from db/senses.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated = models.BooleanField(default=False)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
