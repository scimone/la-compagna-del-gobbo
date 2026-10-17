from django.db import models


class OptionalFeature(models.Model):
    """An optional class feature a player can pick (Eldritch Invocation, Maneuver, Metamagic),
    sourced from `db/optionalfeatures.json`.

    Not part of the original architecture doc's model tree - the source data doesn't fit any of
    the existing catalogs (it's neither a `Feat` nor a per-level `ClassLevel`/`SubclassLevel`
    grant), so it gets its own model instead of being forced into one of those.

    `prerequisite` is a structured `JSONField` list now (class+level, spell-list filter, or nested
    optional-feature references), same treatment as `Feat.prerequisite` and for the same reason.

    `consumes_resource_name` is new: the source names the resource a pick draws from (e.g.
    "Superiority Die" for a Battle Master maneuver) via a `consumes` field - still just a name, no
    amount/recovery (there's no resource catalog anywhere in the source to FK against), but this
    is directly relevant to the "where does spending a `CharacterResource` belong" open design
    question in CLAUDE.md.

    `feature_type` is decoded from the source's short code list (`["EI"]`, `["MM"]`, `["MV:B"]`)
    back to full word(s) at import time (comma-joined if more than one code, though none of the
    current 58 rows have more than one) - this field's shape/values are otherwise unchanged.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated_fields = models.JSONField(default=list, blank=True)
    feature_type = models.CharField(max_length=30)
    prerequisite = models.JSONField(default=list, blank=True)
    consumes_resource_name = models.CharField(max_length=100, blank=True, default="")
    #: The source's `additionalSpells` (an invocation that gives a spell, Pact of the Tome's picks),
    #: same shape as `Feat.additional_spells`.
    additional_spells = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["feature_type", "name"]

    def __str__(self) -> str:
        return self.name
