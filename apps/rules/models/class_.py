from django.db import models


class Class(models.Model):
    """A character class (e.g. Fighter, Wizard), sourced from db/classes.json.

    The numeric level-progression table (which varies per class, e.g. spell slots vs Rages) is
    split out into `ClassLevel` rows, one per level. Per-level feature text (name/entries) isn't
    duplicated here as a `features` JSON field the way it used to be - it lives only as `Feature`
    rows FK'd to the matching `ClassLevel` (`feature.class_level.level` gives the level), the
    same relationship `SubclassLevel` already used - see the "Known data-import issues" section
    of the README (Issue 2, and its follow-up here) for why keeping both was pure duplication
    with no independent reason to exist, once linked rows already have the data.

    `saving_throw_abilities` and `primary_abilities` link to `Ability` instead of keeping
    `savingThrows`/`primaryAbility` as free text. `saving_throws` in the source is always a flat
    "X, Y" pair (both apply), so a plain M2M is enough. `primaryAbility` is trickier - it's
    sometimes one ability ("Wisdom"), sometimes two joined by "or" (a real choice - Fighter can
    build around Strength *or* Dexterity) or "and" (both matter at once - Monk uses Dexterity
    *and* Wisdom for different things) - collapsing that into a bare set would lose which one it
    was, so `primary_ability_conjunction` records it separately (empty when there's only one
    ability). Word order within a pair isn't preserved (`Ability`'s own ordering wins on
    `.all()`), only the ability set and the and/or distinction - the source's phrasing is always
    commutative either way ("Strength or Dexterity" means the same as "Dexterity or Strength"),
    so nothing is actually lost.
    """

    _CONJUNCTIONS = [("and", "and"), ("or", "or")]

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=150, blank=True, default="")
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    hit_die = models.CharField(max_length=10)
    primary_abilities = models.ManyToManyField("rules.Ability", related_name="primary_classes")
    primary_ability_conjunction = models.CharField(
        max_length=3, choices=_CONJUNCTIONS, blank=True, default=""
    )
    saving_throw_abilities = models.ManyToManyField(
        "rules.Ability", related_name="saving_throw_classes"
    )
    proficiencies = models.CharField(max_length=300, blank=True, default="")
    armor_proficiencies = models.CharField(max_length=200, blank=True, default="")
    weapon_proficiencies = models.CharField(max_length=200, blank=True, default="")
    tool_proficiencies = models.CharField(max_length=200, blank=True, default="")
    subclass_title = models.CharField(max_length=100, blank=True, default="")
    lore = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def primary_ability_display(self) -> str:
        names = [a.name for a in self.primary_abilities.all()]
        if len(names) < 2:
            return names[0] if names else ""
        return f" {self.primary_ability_conjunction} ".join(names)

    @property
    def saving_throws_display(self) -> str:
        return ", ".join(a.name for a in self.saving_throw_abilities.all())
