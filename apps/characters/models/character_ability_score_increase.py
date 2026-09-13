from django.db import models


class CharacterAbilityScoreIncrease(models.Model):
    """One line of a Character's ability score history (a base allocation or a later increase).

    Renamed from the architecture doc's "CharacterAbilityScore" - a row here is one contribution
    (e.g. "+2 Wisdom from Background", "+1 Constitution from an ASI at level 4"), not "the
    current Wisdom score". The current, total score is what's actually needed for gameplay
    (ability checks, saves, spell DC, ...), so it lives as a plain field on `Character` instead -
    fast to read, no join, no risk of drifting out of sync with the sum of these rows. This model
    exists so the builder can show/undo *where* each point came from; summing a character's rows
    per ability should always equal that ability's current field value on `Character`.
    """

    ABILITY_CHOICES = [
        ("strength", "Strength"),
        ("dexterity", "Dexterity"),
        ("constitution", "Constitution"),
        ("intelligence", "Intelligence"),
        ("wisdom", "Wisdom"),
        ("charisma", "Charisma"),
    ]

    character = models.ForeignKey(
        "characters.Character", related_name="ability_score_increases", on_delete=models.CASCADE
    )
    ability = models.CharField(max_length=12, choices=ABILITY_CHOICES)
    amount = models.SmallIntegerField()
    source = models.CharField(max_length=100, blank=True, default="")
    granted_at_level = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["character", "granted_at_level"]

    def __str__(self) -> str:
        return f"{self.character}: {self.ability} {self.amount:+d}"
