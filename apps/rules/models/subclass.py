from django.db import models


class Subclass(models.Model):
    """A subclass/archetype of a Class, sourced from `db/classes.json`'s top-level `subclass`
    array (48 rows, already pre-filtered to XPHB, unlike the old nested-and-mixed-source format).

    No `id`/`page`/`srd` fields, same as before - the source still doesn't give subclasses these
    (only a name/`page` exists now, but nothing else this project tracks elsewhere needs it).
    Per-level feature grants live on `SubclassLevel`.

    `description` is the subclass's own flavor text. In the new source, a subclass's
    granting-level feature block is still its own record (in `subclassFeature`, titled after the
    subclass itself) whose `entries` mixes flavor-text strings with `{"type":
    "refSubclassFeature", ...}` pointers to its sibling features - `description` is that block's
    plain-string entries, filtered out at import time; the pointers resolve the real per-level
    `Feature` rows directly, with no unbundling heuristic needed anymore (see the README's "Known
    data-import issues" Issue 1, now structurally fixed by the source itself, and
    `docs/data_migration_2025.md`).
    """

    klass = models.ForeignKey("rules.Class", related_name="subclasses", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.JSONField(default=list, blank=True)
    #: Bonus spells granted by level/delivery mechanism (prepared/known/innate/expanded), sourced
    #: from `db/classes.json`'s `subclass.additionalSpells` - kept as the raw structured JSON
    #: (spell references are already resolvable `"name|source"` keys) rather than a through-model,
    #: since a subclass's granted-spells shape varies by delivery mechanism more than a single
    #: `Spell` M2M could represent cleanly. New: the old format had no such field at all.
    additional_spells = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["klass", "name"]
        constraints = [
            models.UniqueConstraint(fields=["klass", "name"], name="unique_class_subclass"),
        ]

    def __str__(self) -> str:
        return f"{self.klass.name}: {self.name}"
