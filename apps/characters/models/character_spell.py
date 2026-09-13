from django.db import models


class CharacterSpell(models.Model):
    """A Spell a Character knows/has access to.

    `prepared` covers both prepared casters (Cleric/Druid/Wizard/Paladin, where it's meaningful
    and changes) and known casters (Sorcerer/Bard/Warlock/Ranger, where every known spell can
    just be stored as `prepared=True` - the known/prepared distinction for those classes doesn't
    need a second field, it's a service-layer concern, not a schema one).

    `always_prepared` covers spells that don't count against a character's prepared limit (e.g.
    a Cleric's domain spells) - worth its own flag since it's materially different for display
    and for counting purposes, not just a note.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="spells", on_delete=models.CASCADE
    )
    spell = models.ForeignKey("rules.Spell", on_delete=models.PROTECT, related_name="+")
    prepared = models.BooleanField(default=False)
    always_prepared = models.BooleanField(default=False)
    source = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["character", "spell"]
        constraints = [
            models.UniqueConstraint(fields=["character", "spell"], name="unique_character_spell"),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.spell.name}"
