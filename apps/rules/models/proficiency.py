from django.db import models


class Proficiency(models.Model):
    """A proficiency category (weapon/armor/tool/etc.) granted by a Class or Background.

    Populated from the source's own structured proficiency fields, now that they're real JSON
    instead of comma-separated prose: `Class.armor_proficiencies`/`weapon_proficiencies` (flat
    category lists, e.g. `["light", "medium"]`) -> one "armor"/"weapon" row each; `Class.
    tool_proficiencies`/`Background.tools` (still an ad hoc placeholder+count shape per class,
    e.g. `{"anyMusicalInstrument": 3}`, never an enumerated list) -> one "tool" row per entry,
    `name` blank and `choice_data` holding the raw shape - this is the direct structured successor
    to the two cases (Bard's/Monk's tool choices) the old free-text version of this docstring
    described as deliberately excluded entirely; now that they're real JSON rather than
    unparseable "Choose N ..." prose, there's no reason not to keep them.

    `Background.skills` moved off this model entirely - it's a real M2M to `Skill` now (always
    exactly two flat grants in the source, never a choice), so a `Proficiency` row would just
    duplicate it with no independent reason to exist (the same "redundant storage" pattern the
    README's "Known data-import issues" section already calls out for `SubclassLevel.features`/
    `Class.features`).

    `Class`'s skill-choice clause (`startingProficiencies.skills`) is choice-shaped, not a flat
    grant, in the source - see `ChoiceDefinition` for that one instead.

    One nullable FK per possible parent (Class, Background), matching the concrete-FK style used
    elsewhere in this app (`Subclass.klass`, `SubclassLevel.subclass`, ...). Exactly one of
    `klass`/`background` is set per row.
    """

    klass = models.ForeignKey(
        "rules.Class",
        related_name="proficiency_rows",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    background = models.ForeignKey(
        "rules.Background",
        related_name="proficiency_rows",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    category = models.CharField(max_length=20)
    name = models.CharField(max_length=200, blank=True, default="")
    #: The raw ad hoc shape for a proficiency-category *choice* that isn't a flat grant (e.g.
    #: Bard/Monk's tool choices, `{"anyMusicalInstrument": 3}`) - the two cases the docstring above
    #: used to describe as deliberately excluded entirely, now that the new source gives them as
    #: real JSON instead of unparseable "Choose N ..." prose. `name` is blank on these rows.
    choice_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return f"{self.category}: {self.name}"
