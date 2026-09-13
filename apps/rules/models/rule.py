from django.db import models


class Rule(models.Model):
    """A named rule/keyword definition (e.g. Grappling, Cover), sourced from db/rules.json."""

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    rule_type = models.CharField(max_length=50)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
