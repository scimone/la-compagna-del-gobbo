from django.db import models


class Spell(models.Model):
    """A spell definition, sourced from db/spells.json.

    `classes`/`subclasses` list which classes/subclasses can cast the spell, but only as the
    plain names given in the source (e.g. "Artificer" appears here despite not being one of our
    XPHB `Class` rows, and "subclasses" entries are "Class: Subclass" strings) - a hard
    foreign key would either drop that data or invent a matching Class/Subclass row that isn't
    in the source, so these stay plain JSON lists rather than relations. There is no separate
    "spell list" catalog in the source data (see the `rules.SpellList` placeholder).
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    level = models.PositiveSmallIntegerField()
    school = models.CharField(max_length=50)
    casting_time = models.CharField(max_length=100)
    range = models.CharField(max_length=100)
    components = models.CharField(max_length=200)
    duration = models.CharField(max_length=100)
    concentration = models.BooleanField(default=False)
    ritual = models.BooleanField(default=False)
    classes = models.JSONField(default=list, blank=True)
    subclasses = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)
    entries_higher_level = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["level", "name"]

    def __str__(self) -> str:
        return self.name
