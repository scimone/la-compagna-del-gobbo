from django.db import models


class CharacterChoice(models.Model):
    """A resolved builder choice for a Character, keyed by an arbitrary string.

    NOT a FK to `rules.ChoiceDefinition`: that catalog only covers the ~27 choices in the source
    data reliably pattern-shaped enough to parse mechanically (see its docstring). Most real
    character-creation choices - subclass, known spells, expertise, invocations/maneuvers/
    metamagic, "choose A or B" starting equipment - have no such catalog entry and never will
    without inventing structure that isn't in the source. This mirrors how the builder API
    itself is already specified in architecture.md: `PUT /builder/choices/{key}` takes an
    arbitrary key like "fighter.level_8.feat", not a `ChoiceDefinition` id. `value` is
    deliberately a JSON blob since the shape of a resolved choice varies by `key`.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="choices", on_delete=models.CASCADE
    )
    key = models.CharField(max_length=100)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["character", "key"]
        constraints = [
            models.UniqueConstraint(fields=["character", "key"], name="unique_character_choice"),
        ]

    def __str__(self) -> str:
        return f"{self.character}: {self.key}"
