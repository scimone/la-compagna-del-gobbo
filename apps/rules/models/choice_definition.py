from django.db import models


class ChoiceDefinition(models.Model):
    """A choice a player must make, extracted from the source's own structured `{"choose": {...}}`
    objects (`{"from": [...], "count"|"amount": N}`, sometimes `{"weighted": {"from": [...],
    "weights": [...]}}`, sometimes a bare `{"any": N}`) - a genuine idiom the new source uses
    consistently across species/background/class/feat data, replacing the old regex-over-free-text
    approach entirely (the old version of this docstring described parsing "Choose from A, B, C"
    and "Skills: choose N from ..." as the *only* two reliably-pattern-shaped cases in the whole
    old dump; the new source makes this idiom common enough that it's now the normal way choices
    are expressed, not a rare exception).

    Covers, per parent:

    - `Background.ability_scores`: the raw list of alternative weighted spreads (e.g. "+2/+1
      across two of these three" vs "+1/+1/+1 across all three") - `options` holds the whole raw
      list verbatim (each entry keeps its own `from`/`weights`) rather than flattening it into a
      single from/count pair, since a background offers a choice *between* the alternatives, not
      one flat choice.
    - `Class.startingProficiencies.skills`: `options` is the `from` list (skill ids) or empty when
      the source only gives `{"any": N}` (any skill at all, no enumerated subset - e.g. Bard);
      `count` is the literal `count`/`amount`/`any` value either way.
    - `Species.skillProficiencies`/`.feats`/`.resist` (species racial choices) and
      `Feat.ability`/`.savingThrowProficiencies`/`.skillProficiencies` (when choice-shaped, not
      every feat has one): same `options`/`count` extraction, `kind` naming which grant it is
      ("skills", "feats", "resistances", "ability_scores", "saving_throws").

    Not covered (deliberately, for now - see `docs/data_migration_2025.md`): the `{"type":
    "options", ...}` choice nodes that can appear anywhere inside a class/subclass feature's
    `entries` tree (e.g. Cleric's level-1 choice between the "Protector"/"Thaumaturge" features) -
    these resolve to `Feature` rows via `refClassFeature`/`refSubclassFeature` pointers rather than
    a flat option list, which is a different enough shape (and closer to a `builder` prerequisite/
    grant concern than a flat "pick N of these values" choice) to warrant its own pass later
    rather than being forced into this model now.

    One nullable FK per possible parent (Class, Background, Species, Feat), matching the
    concrete-FK style used elsewhere in this app. Exactly one of `klass`/`background`/`species`/
    `feat` is set per row.
    """

    klass = models.ForeignKey(
        "rules.Class",
        related_name="choice_definitions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    background = models.ForeignKey(
        "rules.Background",
        related_name="choice_definitions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    species = models.ForeignKey(
        "rules.Species",
        related_name="choice_definitions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    feat = models.ForeignKey(
        "rules.Feat",
        related_name="choice_definitions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    kind = models.CharField(max_length=30)
    count = models.PositiveSmallIntegerField(null=True, blank=True)
    options = models.JSONField(default=list)
    source_text = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["kind"]

    def __str__(self) -> str:
        return f"{self.kind} ({self.count if self.count is not None else '?'})"
