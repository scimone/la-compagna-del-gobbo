from django.db import models
from django.utils.translation import gettext


class Class(models.Model):
    """A character class (e.g. Fighter, Wizard), sourced from `db/classes.json`'s `class` array.

    The numeric level-progression table (which varies per class, e.g. spell slots vs Rages) is
    split out into `ClassLevel` rows, one per level. Per-level feature text (name/entries) isn't
    duplicated here as a `features` JSON field - it lives only as `Feature` rows FK'd to the
    matching `ClassLevel` (`feature.class_level.level` gives the level) - see the README's "Known
    data-import issues" section (Issue 4) for why keeping both was pure duplication.

    `saving_throw_abilities` and `primary_abilities` link to `Ability` instead of keeping
    `savingThrows`/`primaryAbility` as free text. The source's `primaryAbility` is a list of
    `{ability_code: true}` dicts - genuinely structured now, and the old "one ability, or two
    joined by 'or'/'and'" distinction is derivable directly from its shape rather than needing a
    string-pattern parse: multiple separate dicts means "or" (a real choice - Fighter can build
    around Strength *or* Dexterity, `[{"str": true}, {"dex": true}]`), one dict with multiple keys
    means "and" (both matter at once - Monk, `[{"dex": true, "wis": true}]`), one dict with one key
    means no conjunction (Cleric, `[{"wis": true}]`) - verified against Fighter/Monk/Cleric before
    relying on this. `saving_throws` (source: `class.proficiency`, a flat list, e.g. `["str",
    "con"]`) always means "both apply", so a plain M2M is enough, same as before.

    `armor_proficiencies`/`weapon_proficiencies`/`tool_proficiencies` are the source's own
    structured `startingProficiencies.{armorProficiencies,weaponProficiencies,toolProficiencies}`
    lists now (raw JSON, not comma-separated text) - `armor`/`weapon` are flat category lists
    (`[{"light": true, "medium": true, ...}]`), `tool` stays an ad hoc per-class placeholder shape
    (`[{"anyMusicalInstrument": 3}]`) with no enumerated catalog to resolve against, same as
    `Background.tools`. The skill-choice clause moved to `ChoiceDefinition` (it's genuinely
    choice-shaped, not a flat grant). The old free-text `proficiencies` field (a hand-assembled
    "Armor: ... - Weapons: ... - Skills: choose N from ..." summary string) is dropped entirely -
    every piece of it now lives in a more precise, structured place.

    `spellcasting_ability`/`caster_progression` are new: the source separates these into their own
    fields (`spellcastingAbility`, `casterProgression`: "full"/"1/2"/"1/3"/"pact"/none) instead of
    only baking them into table-row text.

    `lore` has no source in this `db/` drop (no fluff file ships yet) - kept on the model and left
    empty until one is added; see `docs/data_migration_2025.md`.
    """

    _CONJUNCTIONS = [("and", "and"), ("or", "or")]

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    short_description = models.CharField(max_length=150, blank=True, default="")
    page = models.PositiveSmallIntegerField()
    srd = models.BooleanField(default=False)
    self_translated = models.BooleanField(default=False)
    hit_die = models.CharField(max_length=10)
    primary_abilities = models.ManyToManyField("rules.Ability", related_name="primary_classes")
    primary_ability_conjunction = models.CharField(
        max_length=3, choices=_CONJUNCTIONS, blank=True, default=""
    )
    saving_throw_abilities = models.ManyToManyField(
        "rules.Ability", related_name="saving_throw_classes"
    )
    armor_proficiencies = models.JSONField(default=list, blank=True)
    weapon_proficiencies = models.JSONField(default=list, blank=True)
    tool_proficiencies = models.JSONField(default=list, blank=True)
    subclass_title = models.CharField(max_length=100, blank=True, default="")
    spellcasting_ability = models.ForeignKey(
        "rules.Ability",
        related_name="casting_classes",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    caster_progression = models.CharField(max_length=20, blank=True, default="")
    lore = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def primary_ability_display(self) -> str:
        names = [a.name for a in self.primary_abilities.all()]
        if len(names) < 2:
            return names[0] if names else ""
        # `primary_ability_conjunction` is the bare source word ("and"/"or", see `_CONJUNCTIONS`
        # above) - translated here with plain `gettext` (not `apps.frontend.units`, which this
        # app must not depend on - see the README's app-boundary rule) so it still reads "e"/"o"
        # once `Ability.name` itself is Italian.
        return f" {gettext(self.primary_ability_conjunction)} ".join(names)

    @property
    def saving_throws_display(self) -> str:
        return ", ".join(a.name for a in self.saving_throw_abilities.all())
