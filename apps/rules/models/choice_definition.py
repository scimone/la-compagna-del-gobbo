from django.db import models


class ChoiceDefinition(models.Model):
    """A choice a player must make, extracted only where the source text is reliably,
    mechanically pattern-shaped - never by interpreting arbitrary prose.

    Two sources qualify:

    - `Background.ability_scores`: always exactly "Choose from A, B, C" across all 16
      backgrounds. Parsed via a literal match on the "Choose from " prefix; `options` is the
      comma-split remainder. There is no digit anywhere in the source text for how many of the
      three apply (the 2024 rules let you spread +2/+1 or +1/+1/+1 across them), so `count` is
      left null rather than guessing "1" - guessing would be inventing a fact the source doesn't
      state.
    - `Class.proficiencies`' "Skills: choose N from A, B, C" clause: 11 of the 12 classes match
      this literal "choose <digit> from ..." shape; `count` is the literal digit, `options` the
      comma-split remainder. Bard's Skills clause is empty in the source itself (`"Skills: "`,
      nothing after) - a real gap in the data, not a parsing miss - so Bard contributes no row
      here.

    Everything else that reads like a choice in the source was checked and rejected as too
    inconsistent to parse mechanically:

    - Feat benefit text (e.g. Alert's/Keen Mind's/Magic Initiate's named sub-features) phrases
      choices as free prose - "Choose one skill in which...", "Choose one of the following
      skills: ...", "Choose a level 1 spell from the same list...", "Choose a number of level 1
      spells equal to your Proficiency Bonus..." - with no shared template, spelled-out or
      implicit counts, and embedded `{@filter}`/`{@skill}` tags standing in for option lists.
      Parsing these would mean interpreting prose sentence by sentence, not transforming
      already-structured data.
    - `Class`/`Background` tool-proficiency choices ("Choose three Musical Instrument", "Choose
      one type of Artisan's Tools or Musical Instrument") use spelled-out counts and no
      enumerated option list - see `Proficiency` for where those are (deliberately not)
      represented.

    All of the above stays as unparsed text on its existing model field.

    `source_text` keeps the exact matched string so the parse is auditable against the source.
    One nullable FK per possible parent (Class, Background), matching the concrete-FK style used
    elsewhere in this app. Exactly one of `klass`/`background` is set per row.
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
    kind = models.CharField(max_length=30)
    count = models.PositiveSmallIntegerField(null=True, blank=True)
    options = models.JSONField(default=list)
    source_text = models.CharField(max_length=300)

    class Meta:
        ordering = ["kind"]

    def __str__(self) -> str:
        return f"{self.kind} ({self.count if self.count is not None else '?'})"
