from django.conf import settings
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

    `owner` is the account that created the character (D1 in `docs/character_creation_plan.md`):
    every character is *visible* to every account, but only its owner edits or deletes it.
    Nullable because characters created through the plain API have no account, and `SET_NULL` so
    deleting an account never deletes its characters. `status` separates a character still being
    built by the creation wizard (`draft`) from a finished one; the plain API creates `complete`
    ones. `experience_points` is stored (not derived from level) because it is what the player
    actually tracks - the level is derived from it.

    `max_hit_points` IS stored, unlike the derived stats above, because it depends on a genuine
    per-level historical choice (roll-or-average hit dice + Con modifier at each level) that
    isn't a pure function of current state - there's nothing to recompute it from once the
    level-up moment has passed.

    Use `hit_point_maximum` (not `max_hit_points`) wherever the limit in play matters: it is the
    stored maximum minus the reduction a Long Rest removes.
    """

    STATUS_DRAFT = "draft"
    STATUS_COMPLETE = "complete"
    STATUS_CHOICES = [(STATUS_DRAFT, "Draft"), (STATUS_COMPLETE, "Complete")]

    name = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="characters",
    )
    #: The campaign the character plays in: only its members (and administrators) see it.
    #: `PROTECT`: a campaign with characters cannot be deleted.
    campaign = models.ForeignKey(
        "campaigns.Campaign", on_delete=models.PROTECT, related_name="characters"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_COMPLETE)
    experience_points = models.PositiveIntegerField(default=0)
    species = models.ForeignKey(
        "rules.Species", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    background = models.ForeignKey(
        "rules.Background", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    alignment = models.CharField(max_length=30, blank=True, default="")
    size = models.CharField(max_length=20, blank=True, default="")
    #: One free-form text. The creation wizard shows the SRD's "past and present" questions above
    #: the field as a writing guide; the answers are not stored separately.
    backstory = models.TextField(blank=True, default="")
    appearance = models.TextField(blank=True, default="")
    #: The picture the owner uploaded for the sheet (already shrunk and re-encoded by
    #: `characters.services.portrait`), stored under `settings.MEDIA_ROOT`.
    portrait = models.ImageField(upload_to="portraits/", blank=True, default="")
    #: The round avatar (Logbook, ...) is cut from the portrait: `portrait_cx`/`_cy` are the
    #: centre of the cut as fractions of the picture's width/height, `portrait_zoom` (1 = the
    #: largest square that fits, higher = closer). See `portrait.avatar_bytes`.
    portrait_cx = models.FloatField(default=0.5)
    portrait_cy = models.FloatField(default=0.5)
    portrait_zoom = models.FloatField(default=1.0)
    notes = models.TextField(blank=True, default="")

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
    death_save_successes = models.PositiveSmallIntegerField(default=0)
    death_save_failures = models.PositiveSmallIntegerField(default=0)
    #: Spell slots used since the last long rest, `{"<slot level>": n, "pact": n}`. Only what is
    #: *spent* is stored: the maximum is derived from the class levels, so it can never go stale.
    spell_slots_spent = models.JSONField(default=dict, blank=True)
    #: How many prepared spells each class may still swap out, `{"<class id>": n | "any"}` - set by
    #: a long rest or a level (whichever the SRD's "Spell Preparation by Class" table names for
    #: the class) and used up as spells are unprepared. No entry: the list is locked until then.
    spell_changes = models.JSONField(default=dict, blank=True)

    # `{class id: 1}`: the classes whose Weapon Mastery weapons may be changed now (after a rest).
    weapon_mastery_changes = models.JSONField(default=dict, blank=True)
    # The conditions on the character (`["blinded", ...]`, see `characters/conditions.py`) and its
    # Exhaustion level (0-6): the one condition whose effects stack.
    conditions = models.JSONField(default=list, blank=True)
    exhaustion = models.PositiveSmallIntegerField(default=0)
    # Choices a Long Rest opens until they are made, `{"land": True}` (Circle of the Land's new
    # land - see `apps/builder/services/land.py`).
    rest_choices = models.JSONField(default=dict, blank=True)
    # The once-per-Long-Rest spell slot recoveries used (`["Arcane Recovery"]`, Natural Recovery).
    spell_recoveries_used = models.JSONField(default=list, blank=True)
    # Reductions that last until a Long Rest (a monster's drain): taken off the maximum hit points
    # and off the ability scores (`{"str": 2}`). The stored values stay the full ones.
    max_hit_points_reduction = models.PositiveSmallIntegerField(default=0)
    ability_reductions = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def hit_point_maximum(self) -> int:
        return max(0, self.max_hit_points - self.max_hit_points_reduction)
