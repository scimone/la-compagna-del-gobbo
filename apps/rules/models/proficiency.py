from django.db import models


class Proficiency(models.Model):
    """A proficiency category (weapon/armor/save/etc.) granted by a Class or Background.

    Populated by splitting the known comma-separated proficiency fields into individual items:
    `Class.armor_proficiencies` -> category "armor", `Class.weapon_proficiencies` -> "weapon",
    `Class.tool_proficiencies` -> "tool", `Background.skills` -> "skill", `Background.tools` ->
    "tool". `category` is derived purely from which source field the text came from, never from
    interpreting the text itself - so e.g. "Martial weapons that have the Light property" (from
    Monk's `weapon_proficiencies`) becomes one "weapon" row verbatim, not something parsed
    further.

    Deliberately excluded: any comma-separated item whose text starts with "Choose" (case
    insensitive) - that's a choice, not a flat grant. The only two occurrences in the source are
    Bard's and Monk's `tool_proficiencies` ("Choose three Musical Instrument", "Choose one type
    of Artisan's Tools or Musical Instrument") - folding either into a plain `Proficiency` row
    would misrepresent it as an unconditional grant. Those two strings aren't reliably
    pattern-shaped enough to feed `ChoiceDefinition` either (see that model's docstring - they
    use spelled-out counts and no enumerated option list), so they simply aren't represented
    anywhere beyond the raw `Class.tool_proficiencies` text they already live in.

    `Class.proficiencies`' own "Skills: choose N from ..." clause is *always* choice-shaped in
    the source (never a flat list, for any of the 12 classes), so it contributes zero
    `Proficiency` rows - see `ChoiceDefinition` for that one instead.

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
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return f"{self.category}: {self.name}"
