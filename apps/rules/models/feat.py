from django.db import models


class Feat(models.Model):
    """A feat (e.g. Alert, Tough), sourced from `db/feats.json`.

    `prerequisite` is a structured `JSONField` list now (`{level, ability, feature, proficiency,
    otherSummary}` objects) instead of one free-text string - the old string was flagged in the
    README as never checked for the "should this be a FK" pattern, and it turns out the new
    source is strictly more complete in at least one case (Agonizing Blast's old prose omitted a
    level-2 requirement the new structured `level` field makes explicit). Kept as JSON rather than
    several dedicated columns since the shape is genuinely heterogeneous per entry (ability
    minimums, level, a prior feature, a proficiency, or a prose fallback, mixed per prerequisite).

    A `feature`-shaped prerequisite entry (e.g. Fighting Style feats' `{"feature": ["Fighting
    Style"]}`) names a generic feature *category*, not a specific other `Feat` - confirmed across
    every occurrence in the source (10 rows, all "Fighting Style") - so there's no real "does the
    builder already have feat X" FK to extract here; it stays inside the raw `prerequisite` JSON.

    `additional_spells` (the source's `additionalSpells`, e.g. Magic Initiate's per-list "two
    cantrips + one level-1 spell, spellcasting ability Int/Wis/Cha") and `grants` (whichever of the
    source's proficiency-grant keys the feat has, verbatim: `skillProficiencies`,
    `toolProficiencies`, `weaponProficiencies`, `armorProficiencies`, `savingThrowProficiencies`,
    `skillToolLanguageProficiencies`, `expertise`, `senses`, `resist`) were added for the character
    builder - an Origin feat's sub-choices (Skilled: "any 3 skills or tools", Musician: "3
    instruments", Crafter: "3 artisan tools") are otherwise only English prose. Ability-score
    choices stay in `ChoiceDefinition`.

    `ability` is the source's `ability` list verbatim (`[{"cha": 1}]` or `[{"choose": {"from":
    [...]}, "max": 30}]`) - the feat's ability score increase, which the source keeps out of
    `entries`; the feat's page renders it as a fact.

    `category` is decoded from the source's short code (`O`/`G`/`FS`/`EB`/...) back to the full
    word at import time, so this field's shape/values are unchanged from before.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated_fields = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=30)
    prerequisite = models.JSONField(default=list, blank=True)
    ability = models.JSONField(default=list, blank=True)
    additional_spells = models.JSONField(default=list, blank=True)
    grants = models.JSONField(default=dict, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
