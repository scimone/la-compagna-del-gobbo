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

    `klass` is the class this spell belongs to: the SRD's multiclass rule is that each prepared
    spell is associated with one of the character's classes and cast with *that* class's
    spellcasting ability. Null for spells that come from elsewhere (a species, a feat), whose
    ability is then recorded via `source`/`CharacterChoice`. `in_spellbook` is the Wizard's
    spellbook: it holds more spells than the wizard has prepared, so "known" and "prepared" are
    genuinely different sets for that class.

    `free_cast` marks a spell that can be cast once without a spell slot (Magic Initiate's level 1
    spell: "you regain the ability to cast it in that way when you finish a Long Rest"); the slot
    can still be used as usual. `free_cast_used` is that one use, spent. `free_cast_unlimited` is a
    spell the character can cast without a slot as often as they like (an Eldritch Invocation's
    "You can cast Mage Armor on yourself without expending a spell slot"); it never runs out.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="spells", on_delete=models.CASCADE
    )
    spell = models.ForeignKey("rules.Spell", on_delete=models.PROTECT, related_name="+")
    prepared = models.BooleanField(default=False)
    always_prepared = models.BooleanField(default=False)
    klass = models.ForeignKey(
        "rules.Class", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    in_spellbook = models.BooleanField(default=False)
    source = models.CharField(max_length=100, blank=True, default="")
    free_cast = models.BooleanField(default=False)
    free_cast_used = models.BooleanField(default=False)
    free_cast_unlimited = models.BooleanField(default=False)

    class Meta:
        ordering = ["character", "spell"]
        constraints = [
            models.UniqueConstraint(fields=["character", "spell"], name="unique_character_spell"),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.spell.name}"
