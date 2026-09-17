from django.db import models


class Spell(models.Model):
    """A spell definition, sourced from `db/spells.json`.

    `casting_time`/`range`/`duration`/`components` are structured `JSONField`s now, not display
    strings - the new source gives them as nested objects (`range`: `{"type": "point", "distance":
    {"type": "feet", "amount": 120}}`, etc.) and flattening them back to a string at import time
    would re-derive display text with no way to recover the structure later. Rendering these for
    display is a template/service concern now, not an import concern. `concentration`/`ritual`
    stay plain booleans, derived at import time (`concentration` from any `duration[].concentration`
    being true, `ritual` from `meta.ritual`) since the source moved them out of top-level fields.

    `saving_throw_abilities` is new - the source's `savingThrow` field gives real ability
    references where the old format had none at all. A plain M2M, not a single nullable FK: most
    spells (146/391) name exactly one, but 8 (e.g. Earthquake, Prismatic Spray) name two or three
    (a target can choose, or different effects call for different saves) - verified across all
    391 entries before assuming a single FK would suffice; it wouldn't.

    `classes`/`subclasses` list which classes/subclasses can cast the spell, but the new source
    dropped this data entirely (confirmed: no `classes`/`subclasses`-shaped field anywhere in
    `db/spells.json`, and no replacement - `db/classes.json`'s `additionalSpells` only covers
    bonus/granted spells, not full spell-list eligibility). Since all 391 spell names match
    exactly between `db/spells.json` and `db_old/spells.json`, these two fields are populated from
    `db_old/spells.json`'s arrays instead - a deliberate, frozen exception to "only `db/` is live
    source data", kept until upstream ships a real replacement (see
    `docs/data_migration_2025.md`). Still plain JSON lists, not relations, for the same reason as
    before: a hard FK would either drop data (e.g. "Artificer", not one of our XPHB `Class` rows)
    or invent a matching row the source doesn't give.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    level = models.PositiveSmallIntegerField()
    school = models.CharField(max_length=50)
    casting_time = models.JSONField(default=list, blank=True)
    range = models.JSONField(default=dict, blank=True)
    components = models.JSONField(default=dict, blank=True)
    duration = models.JSONField(default=list, blank=True)
    concentration = models.BooleanField(default=False)
    ritual = models.BooleanField(default=False)
    saving_throw_abilities = models.ManyToManyField(
        "rules.Ability", related_name="spells", blank=True
    )
    classes = models.JSONField(default=list, blank=True)
    subclasses = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)
    entries_higher_level = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["level", "name"]

    def __str__(self) -> str:
        return self.name
