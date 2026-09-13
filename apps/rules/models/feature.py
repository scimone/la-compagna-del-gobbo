from django.db import models


class Feature(models.Model):
    """A discrete class/subclass/species/feat feature grant.

    Populated from the already-structured, explicitly named `{name, entries}` (or `{level, name,
    entries}`) dicts nested inside four parents' source JSON:

    - `Class.features` (db/classes.json, top-level list items - every one carries `level`,
      `name` and `entries`, no bare strings mixed in).
    - `SubclassLevel.features` (same source, subclass `features` grouped by level - only the 48
      XPHB-sourced subclasses, matching `Subclass`/`SubclassLevel`).
    - `Species.entries` (db/species.json, the 10 XPHB species only, matching `Species`).
    - `Feat.entries` (db/feats.json) - here the source lists mix bare prose strings with named
      dicts (e.g. Alert's entries are one prose paragraph plus two named benefits, "Initiative
      Proficiency" and "Initiative Swap"); only the named dicts become `Feature` rows, the prose
      strings are left alone on `Feat.entries`.

    Only list items that are dicts with an explicit `name` key are lifted - bare prose strings
    mixed into the same lists are left untouched on the parent, since turning them into a
    "Feature" would invent a name/boundary the source doesn't give. Nothing is recursed *into*:
    an extracted `entries` value is stored verbatim (including any further-nested dicts it
    contains), it is not walked for more named sub-blocks - so e.g. Barbarian's "Rage" becomes
    one `Feature` row whose `entries` still contains its nested "Damage Resistance"/"Rage
    Damage"/"Strength Advantage" blocks inline, rather than three more `Feature` rows for those
    (drawing that boundary at an arbitrary recursion depth felt more like invented structure than
    a mechanical transform).

    `OptionalFeature.entries` was checked too: none of its top-level list items carry a `name`
    key (the handful of dict items there are unnamed `{"type": "entries", "entries": [...]}`
    wrappers around nested named sub-blocks, e.g. "Repeatable"), so - by the same
    top-level-only rule - it contributes zero `Feature` rows.

    This *duplicates* data still held verbatim in the parent's own JSON field (`Class.features`,
    `SubclassLevel.features`, `Species.entries`, `Feat.entries`). Those parent models are
    out of scope for this pass (already "Defined" and verified), so their raw fields can't be
    replaced the way `Subclass.features` was replaced by `SubclassLevel` - `Feature` is
    therefore an additive, queryable index over the same data, not the sole source of truth
    for it.

    One nullable FK per possible parent (rather than a `GenericForeignKey`) to match the
    concrete-FK style already used elsewhere in this app (`Subclass.klass`,
    `SubclassLevel.subclass`, ...). Exactly one of `klass`/`subclass_level`/`species`/`feat` is
    set per row.
    """

    klass = models.ForeignKey(
        "rules.Class",
        related_name="feature_rows",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    subclass_level = models.ForeignKey(
        "rules.SubclassLevel",
        related_name="feature_rows",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    species = models.ForeignKey(
        "rules.Species",
        related_name="feature_rows",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    feat = models.ForeignKey(
        "rules.Feat",
        related_name="feature_rows",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    level = models.PositiveSmallIntegerField(null=True, blank=True)
    name = models.CharField(max_length=200)
    entries = models.JSONField(default=list)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
