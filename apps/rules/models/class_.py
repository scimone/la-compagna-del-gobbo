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
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=150, blank=True, default="")
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    hit_die = models.CharField(max_length=10)
    primary_ability = models.CharField(max_length=100)
    saving_throws = models.CharField(max_length=100)
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
