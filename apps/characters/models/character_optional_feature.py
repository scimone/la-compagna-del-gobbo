from django.db import models


class CharacterOptionalFeature(models.Model):
    """An optional class feature a Character has picked - an Eldritch Invocation, a Battle
    Master Maneuver, or a Metamagic option (see `rules.OptionalFeature`).

    Added to the model tree beyond architecture.md's original list: `rules.OptionalFeature`
    didn't exist yet when that list was drafted, and these are genuine player picks with nowhere
    else to live. Unlike `CharacterFeat`, these are each individually unique picks in the source
    rules (you don't take the same Invocation/Maneuver/Metamagic option twice), so uniqueness is
    enforced here.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="optional_features", on_delete=models.CASCADE
    )
    optional_feature = models.ForeignKey(
        "rules.OptionalFeature", on_delete=models.PROTECT, related_name="+"
    )
    granted_at_level = models.PositiveSmallIntegerField(null=True, blank=True)
    #: `"sheet"` for an option the player added by hand from the character sheet (see
    #: `CharacterFeature.source`); blank for a builder pick.
    source = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["character", "granted_at_level"]
        constraints = [
            models.UniqueConstraint(
                fields=["character", "optional_feature"],
                name="unique_character_optional_feature",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.optional_feature.name}"
