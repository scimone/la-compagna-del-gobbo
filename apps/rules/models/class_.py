from django.db import models


class Class(models.Model):
    """A character class (e.g. Fighter, Wizard), sourced from db/classes.json.

    `features` holds the raw {level, name, entries} list from the source (feature text by
    level); the numeric level-progression table (which varies per class, e.g. spell slots vs
    Rages) is instead split out into `ClassLevel` rows, one per level.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
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
    features = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
