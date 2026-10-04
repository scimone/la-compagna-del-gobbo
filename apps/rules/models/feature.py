from django.db import models


class Feature(models.Model):
    """A discrete class/subclass/species/feat feature grant.

    Populated from the already-structured, explicitly named `{name, entries}` (or `{level, name,
    entries}`) dicts nested inside four parents' source JSON:

    - A `Class`'s per-level features (db/classes.json, top-level `features` list items - every
      one carries `level`, `name` and `entries`, no bare strings mixed in) - FK'd to the
      matching `ClassLevel` (by its `level`), not to `Class` directly, and not duplicated as a
      `Class.features` JSON field either - see `ClassLevel`'s docstring and the "Known
      data-import issues" section of the README.
    - A `Subclass`'s per-level features (same source, `db/classes.json` subclass `features`
      grouped by level - only the 48 XPHB-sourced subclasses, matching `Subclass`/
      `SubclassLevel`) - FK'd to the matching `SubclassLevel` the same way, for the same reason.
    - `Species.entries` (db/species.json - the 10 XPHB species plus `Grung`, matching `Species`;
      see that model's docstring for why `Grung` is there despite not being XPHB).
    - `Feat.entries` (db/feats.json) - here the source lists mix bare prose strings with named
      dicts (e.g. Alert's entries are one prose paragraph plus two named benefits, "Initiative
      Proficiency" and "Initiative Swap"); only the named dicts become `Feature` rows, the prose
      strings are left alone on `Feat.entries`.

    Both class and subclass features are created directly by `_import_classes` (see
    `_split_subclass_features` in `apps/rules/management/commands/import_rules_data.py`), not
    walked from a stored JSON field the way the other two sources are.

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

    For the last two sources, this *duplicates* data still held verbatim in the parent's own
    JSON field (`Species.entries`, `Feat.entries`). Those parent models are out of scope for
    this pass (already "Defined" and verified), so their raw fields weren't replaced - `Feature`
    is an additive, queryable index over the same data for those two, not the sole source of
    truth for it. Class and subclass features are the exception: there's no `ClassLevel.features`
    or `SubclassLevel.features` to duplicate, so `Feature` *is* the sole source of truth for
    those.

    No separate `level` field either - it would just repeat `class_level.level`/
    `subclass_level.level` for the two sources that have one, and is meaningless (always empty)
    for the two that don't.

    One nullable FK per possible parent (rather than a `GenericForeignKey`) to match the
    concrete-FK style already used elsewhere in this app (`Subclass.klass`,
    `SubclassLevel.subclass`, ...). Exactly one of `class_level`/`subclass_level`/`species`/
    `feat` is set per row.
    """

    class_level = models.ForeignKey(
        "rules.ClassLevel",
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
    name = models.CharField(max_length=200)
    #: Names the resource this feature spends (e.g. "Channel Divinity"), from the source's
    #: `consumes` field on `classFeature`/`subclassFeature` entries - see
    #: `OptionalFeature.consumes_resource_name` for why this is a bare name, not a FK.
    consumes_resource_name = models.CharField(max_length=100, blank=True, default="")
    #: One alternative of a choice made inside a parent feature (Divine Order's Protector/
    #: Thaumaturge, a species lineage, Circle of the Land's land type). It is granted to the
    #: characters that chose it and stays in the World features list, but the class/subclass
    #: pages' level views leave it out - next to its siblings it would read as if every character
    #: got all of them.
    choice_option = models.BooleanField(default=False)
    entries = models.JSONField(default=list)
    #: Which of this row's own translated field names (`"name"`, `"entries"`) were hand-translated
    #: for this project rather than lifted from an official Italian source (the SRD PDF, for
    #: everything else translated so far) - e.g. `["entries"]` if only the body text is hand-
    #: translated but the name came from the SRD. Set from `apps.rules.translation_sync`'s `_self`
    #: overlay list at sync time. Every translated model in `TRANSLATED_CATALOGS` carries the same
    #: field, under the same name.
    self_translated_fields = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
