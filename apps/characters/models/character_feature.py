from django.db import models


class CharacterFeature(models.Model):
    """An automatic Feature grant active on a Character (Rage, Second Wind, Darkvision-granting
    species traits, ...).

    Distinct from `CharacterFeat`: a Feature is granted automatically by a class/subclass/
    species/feat the character already has, never chosen on its own. `feature` (`rules.Feature`)
    already records which parent granted it (its `klass`/`subclass_level`/`species`/`feat` FK),
    so this row doesn't duplicate that provenance - it just says "this Feature is active for
    this Character" plus the level at which it actually unlocked for them (which can differ from
    the Feature's own recorded level once multiclassing is involved).
    """

    character = models.ForeignKey(
        "characters.Character", related_name="features", on_delete=models.CASCADE
    )
    feature = models.ForeignKey("rules.Feature", on_delete=models.PROTECT, related_name="+")
    granted_at_level = models.PositiveSmallIntegerField(null=True, blank=True)
    #: `"sheet"` for a Feature the player added by hand from the character sheet (the only kind
    #: that can be taken away again there - see `play.add_feature`); blank for a builder grant.
    source = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["character", "granted_at_level"]
        constraints = [
            models.UniqueConstraint(
                fields=["character", "feature"], name="unique_character_feature"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.feature.name}"
