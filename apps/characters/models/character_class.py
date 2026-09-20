from django.db import models


class CharacterClass(models.Model):
    """A class/subclass a Character has levels in.

    One row per distinct class a character has taken levels in - multiple rows per character
    is how multiclassing is represented (e.g. Fighter 3 / Rogue 2 is two rows). `subclass` is
    nullable since it isn't chosen until the class's subclass-selection level is reached.

    `is_starting_class` marks the class the character began with: only that one grants level-1
    hit points and the full set of starting proficiencies (multiclass rules, SRD "Multiclasse").
    `hit_dice_spent` counts the Hit Dice of *this* class spent on short rests, so pools of
    different die sizes (Cleric d8 + Paladin d10) stay separate, as the SRD requires.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="classes", on_delete=models.CASCADE
    )
    klass = models.ForeignKey("rules.Class", on_delete=models.PROTECT, related_name="+")
    subclass = models.ForeignKey(
        "rules.Subclass", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    level = models.PositiveSmallIntegerField(default=1)
    is_starting_class = models.BooleanField(default=False)
    hit_dice_spent = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["character", "-level"]
        constraints = [
            models.UniqueConstraint(fields=["character", "klass"], name="unique_character_class"),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.klass.name} {self.level}"
