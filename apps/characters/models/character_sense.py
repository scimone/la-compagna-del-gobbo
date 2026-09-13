from django.db import models


class CharacterSense(models.Model):
    """A special sense a Character has (see `rules.Sense`), with its granted range.

    `range_feet` lives here rather than on `rules.Sense`: the same sense (e.g. Darkvision) is
    granted at different ranges by different sources (a species trait vs. a feat), so the range
    is a property of the grant, not of the sense itself. Multiple rows for the same
    (character, sense) are allowed on purpose - e.g. two sources both granting Darkvision at
    different ranges - resolving that down to "the best one applies" is a `derived_stats`
    concern, not something to force into a uniqueness constraint here.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="senses", on_delete=models.CASCADE
    )
    sense = models.ForeignKey("rules.Sense", on_delete=models.PROTECT, related_name="+")
    range_feet = models.PositiveSmallIntegerField(null=True, blank=True)
    source = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["character", "sense"]

    def __str__(self) -> str:
        return f"{self.character}: {self.sense.name}"
