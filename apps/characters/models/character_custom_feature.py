from django.db import models


class CharacterCustomFeature(models.Model):
    """A feature the player made up (a homebrew trait, a boon from the story) - not a
    `rules.Feature`, which is read-only catalog data. Its `effects` (see
    `characters.custom_effects`) are always in force, like a class feature's; the text is only
    shown."""

    character = models.ForeignKey(
        "characters.Character", related_name="custom_features", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    effects = models.JSONField(default=list, blank=True)
    #: Ids of `rules.Spell`s this grants, always prepared - a feature's always, an item's while worn
    #: (`play.sync_custom_spells` keeps the character's `CharacterSpell` rows in step).
    spells = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["character", "name"]

    def __str__(self) -> str:
        return f"{self.character}: {self.name}"
