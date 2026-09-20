from django.db import models


class Ability(models.Model):
    """One of the six core ability scores (Strength, Dexterity, Constitution, Intelligence,
    Wisdom, Charisma), sourced from db/handbook.json's "Ability Descriptions" table (Chapter 1
    -> The Six Abilities) - not hand-written, since that table already gives exactly this data.

    Referenced by `Skill.ability` (one each) and `Class.primary_abilities`/
    `saving_throw_abilities` (a class can have more than one of either - see `Class`'s docstring
    for how the "or"/"and" distinction in `primaryAbility` is preserved instead of flattened
    into an unordered set).
    """

    id = models.SlugField(primary_key=True, max_length=20)
    name = models.CharField(max_length=20)
    description = models.CharField(max_length=200)
    self_translated = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
