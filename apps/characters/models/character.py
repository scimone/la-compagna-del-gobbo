from django.db import models


class Character(models.Model):
    """A player character.

    `species`/`background` are nullable because the builder creates a `Character` row up front
    and fills in steps incrementally (see architecture.md's builder state: "steps" with
    complete: false) - a character can legitimately exist mid-creation with neither set yet.

    Deliberately NOT stored here: total level (derive from `sum(classes.values_list("level"))`
    - a character's classes are the source of truth, a cached total would just go stale) or any
    derived stat like AC, initiative, spell save DC or passive Perception (all computed from
    ability scores + proficiencies + features by `builder.services.derived_stats`, never
    persisted, for the same reason).

    `max_hit_points` IS stored, unlike the derived stats above, because it depends on a genuine
    per-level historical choice (roll-or-average hit dice + Con modifier at each level) that
    isn't a pure function of current state - there's nothing to recompute it from once the
    level-up moment has passed.
    """

    name = models.CharField(max_length=100)
    species = models.ForeignKey(
        "rules.Species", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    background = models.ForeignKey(
        "rules.Background", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    alignment = models.CharField(max_length=30, blank=True)
    size = models.CharField(max_length=20, blank=True)
    appearance = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    strength = models.PositiveSmallIntegerField(default=10)
    dexterity = models.PositiveSmallIntegerField(default=10)
    constitution = models.PositiveSmallIntegerField(default=10)
    intelligence = models.PositiveSmallIntegerField(default=10)
    wisdom = models.PositiveSmallIntegerField(default=10)
    charisma = models.PositiveSmallIntegerField(default=10)

    max_hit_points = models.PositiveSmallIntegerField(default=0)
    current_hit_points = models.PositiveSmallIntegerField(default=0)
    temporary_hit_points = models.PositiveSmallIntegerField(default=0)

    inspiration = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
