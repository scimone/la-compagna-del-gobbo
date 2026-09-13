from django.db import models


class CharacterFeat(models.Model):
    """A Feat a Character has chosen (background feat, general feat at an ASI level, epic boon).

    Added to the model tree beyond architecture.md's original list: a Feat is a player *choice*,
    unlike a `CharacterFeature` grant, and had no home before this - it was being conflated with
    `CharacterFeature`, which only covers automatic grants.

    No uniqueness constraint on (character, feat): confirmed against the source data that at
    least one feat is explicitly repeatable - "Ability Score Improvement" states "You can take
    this feat more than once" in its own `entries` (db/feats.json) - so forbidding a second row
    for the same feat would be wrong, not just overly strict.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="feats", on_delete=models.CASCADE
    )
    feat = models.ForeignKey("rules.Feat", on_delete=models.PROTECT, related_name="+")
    granted_at_level = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["character", "granted_at_level"]

    def __str__(self) -> str:
        return f"{self.character}: {self.feat.name}"
