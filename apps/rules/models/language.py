from django.db import models


class Language(models.Model):
    """A language (e.g. Common, Elvish), sourced from db/languages.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    language_type = models.CharField(max_length=20)
    script = models.CharField(max_length=100, blank=True, default="")
    typical_speakers = models.CharField(max_length=200, blank=True, default="")
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
