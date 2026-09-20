from django.db import models


class Species(models.Model):
    """A player species (e.g. Elf, Dwarf), sourced from `db/species.json`.

    `size`/`creature_types` are code lists now (`["S", "M"]`, `["humanoid"]`), not prose
    (`"Small or Medium"`, `"Humanoid"`) - no catalog exists for these (both are small, fixed
    enums), so they're kept as `JSONField` lists rather than invented FK targets.

    `fly_speed`/`swim_speed`/`climb_speed` are dropped: the new source has no such fields at all
    (only a flat `speed`), and this is verified to lose no real data - every one of the 10 XPHB
    species already had all three at 0 in the old dump. `Grung` (added back by hand afterward -
    see `SPECIES_SHORT_DESCRIPTIONS` in `import_rules_data.py` - it isn't XPHB, so wasn't in the
    new source drop this project otherwise imports verbatim) is the one exception: its old
    `swimSpeed` equaled its `walkSpeed` exactly, so dropping it is still lossless - "Swimming
    Instinct" already says as much in its own `entries` prose. `speed` becomes a plain int (was
    `"30 ft."` display text; also collapses what used to be a second, fully redundant field - the
    old `speed`/`walk_speed` pair always held the same value two ways).

    `darkvision` is new - the old format only expressed this as unparsed prose inside `entries`.

    `parent_race` is dropped: the 2024 rules have no subraces (already noted in the README), and
    the new source's `parentRace`-equivalent field doesn't appear on any entry.

    `lore` has no source in this `db/` drop (no fluff file ships yet) - kept on the model and left
    empty until one is added; see `docs/data_migration_2025.md`.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=150, blank=True, default="")
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    size = models.JSONField(default=list, blank=True)
    speed = models.PositiveSmallIntegerField(default=30)
    darkvision = models.PositiveSmallIntegerField(default=0)
    creature_types = models.JSONField(default=list, blank=True)
    lore = models.JSONField(default=list, blank=True)
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "species"

    def __str__(self) -> str:
        return self.name
