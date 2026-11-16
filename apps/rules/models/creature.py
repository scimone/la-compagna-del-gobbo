from django.db import models


class Creature(models.Model):
    """A stat block of the SRD's Appendix B (Ape ... Zombie), from `db/creatures.json`.

    The Druid's Wild Shape picks its known forms from the Beasts among them
    (`apps/builder/services/wild_shape.py`). Plain text and rules data only: nothing here is
    translated (the stat blocks are shown in English on the Italian site too).

    `speed` is `{"walk": 30, "climb": 30, ...}` in feet; `abilities` is `{"str": {"score", "mod"}}`;
    `traits`/`actions`/`bonus_actions`/`reactions` are lists of `{"type": "entries", "name",
    "entries"}` that `entries_render` shows like any other rules text. `cr_value` is the Challenge
    Rating as a number (1/4 -> 0.25) so forms can be compared against Wild Shape's limit.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    size = models.CharField(max_length=20)
    type = models.CharField(max_length=40)
    subtype = models.CharField(max_length=60, blank=True, default="")
    alignment = models.CharField(max_length=60, blank=True, default="")
    ac = models.PositiveSmallIntegerField()
    initiative_modifier = models.SmallIntegerField(default=0)
    initiative_score = models.PositiveSmallIntegerField(default=10)
    hp_average = models.PositiveSmallIntegerField()
    hp_formula = models.CharField(max_length=40)
    speed = models.JSONField(default=dict, blank=True)
    speed_text = models.CharField(max_length=200, blank=True, default="")
    abilities = models.JSONField(default=dict, blank=True)
    skills = models.JSONField(default=dict, blank=True)
    vulnerabilities = models.CharField(max_length=200, blank=True, default="")
    resistances = models.CharField(max_length=200, blank=True, default="")
    immunities = models.CharField(max_length=200, blank=True, default="")
    senses = models.CharField(max_length=300, blank=True, default="")
    languages = models.CharField(max_length=300, blank=True, default="")
    gear = models.CharField(max_length=200, blank=True, default="")
    cr = models.CharField(max_length=10)
    cr_value = models.FloatField()
    xp = models.PositiveIntegerField(default=0)
    proficiency_bonus = models.PositiveSmallIntegerField(default=2)
    traits = models.JSONField(default=list, blank=True)
    actions = models.JSONField(default=list, blank=True)
    bonus_actions = models.JSONField(default=list, blank=True)
    reactions = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def has_fly_speed(self) -> bool:
        return "fly" in (self.speed or {})
