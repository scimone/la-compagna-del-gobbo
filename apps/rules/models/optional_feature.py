from django.db import models


class OptionalFeature(models.Model):
    """An optional class feature a player can pick (Eldritch Invocation, Maneuver, Metamagic),
    sourced from db/optional_features.json.

    Not part of the original architecture doc's model tree - the source data doesn't fit any of
    the existing catalogs (it's neither a `Feat` nor a per-level `ClassLevel`/`SubclassLevel`
    grant), so it gets its own model instead of being forced into one of those.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    feature_type = models.CharField(max_length=30)
    prerequisite = models.CharField(max_length=200, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["feature_type", "name"]

    def __str__(self) -> str:
        return self.name
