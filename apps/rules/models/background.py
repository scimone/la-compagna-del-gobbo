from django.db import models


class Background(models.Model):
    """A character background (e.g. Soldier, Sage), sourced from `db/backgrounds.json`.

    `ability_scores` keeps the raw structured choice list from the source (each item shaped like
    `{"choose": {"weighted": {"from": [...], "weights": [...]}}}` - a background offers a choice
    *between* these alternative spreads) rather than flattening it into a display string - the
    weights are real information (which of "+2/+1" vs "+1/+1/+1" the source now spells out
    explicitly) that a free-text field would lose. `skills` is a real M2M now (was a "Athletics,
    Intimidation" comma string) since a background's skill grants are never a choice - always
    exactly two flat grants - and the source now gives real skill ids. `tools`/`feat` are
    populated from the source's own structured references: `tools` stays `JSONField` (still an ad
    hoc placeholder+count shape, e.g. `{"anyGamingSet": 1}`, not an enumerated list - same
    unresolved shape `Class.tool_proficiencies` has); `feat` becomes a real FK now that the source
    gives the granted feat as a resolvable `"name|source"` reference instead of a bare string.

    `starting_equipment` (a background's `A`/`B` equipment-or-gold choice) is new - the old format
    only had this as unparsed prose - modeled via `BackgroundStartingEquipmentOption` rows rather
    than a JSON blob, so each granted item is a real `Equipment` FK.

    `lore` has no source in this `db/` drop (no fluff file ships yet) - kept on the model and left
    empty until one is added; see `docs/data_migration_2025.md`.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated_fields = models.JSONField(default=list, blank=True)
    ability_scores = models.JSONField(default=list, blank=True)
    skills = models.ManyToManyField("rules.Skill", related_name="backgrounds", blank=True)
    tools = models.JSONField(default=list, blank=True)
    feat = models.ForeignKey(
        "rules.Feat",
        related_name="granting_backgrounds",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    lore = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
