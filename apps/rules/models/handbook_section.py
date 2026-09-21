from django.db import models

from .handbook_chapter import HandbookChapter


class HandbookSection(models.Model):
    """A named topic of the handbook, sourced from db/handbook.json.

    db/handbook.json has one level-1 item per chapter ("Playing the Game", "Character Origins",
    ...), each modelled as a `HandbookChapter`. A chapter's direct named children ("Dice",
    "Character Backgrounds", "Weapons", ... - a mix of the source's `section` and `inset` types,
    both treated the same here) each become one row of this table, pointing at their chapter; the
    chapter's own unnamed leading content (the "Playing the Game" intro narrative) is not kept.
    Deeper named blocks stay inside `entries`, rendered as toggle headings.

    `name`/`entries` are translated (`name_en`/`name_it`, ...; see `apps/rules/translation.py`).
    Rows and blocks that have no Italian text are left out of the import for both languages -
    see `apps/rules/handbook_source.py` - so this table holds fewer rows than the source has.

    `self_translated_fields` lists which of the row's translated fields (`"name"`, `"entries"`)
    were hand-translated for this project rather than taken from the official Italian SRD - same
    meaning as on the catalog models. Inside `entries`, an individual hand-translated block
    carries its own `"self_translated": true` (Italian side only, see `handbook_source`).
    """

    id = models.SlugField(primary_key=True, max_length=100)
    chapter = models.ForeignKey(HandbookChapter, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    entries = models.JSONField(default=list, blank=True)
    self_translated_fields = models.JSONField(default=list, blank=True)

    class Meta:
        # Chapters come in document order, and inside one, `id` (e.g. "008", "00c", ...) is a
        # same-length hex-ish code assigned in document order by the source, so sorting by it (as
        # a plain string) reproduces reading order - `page` alone has ties (e.g. "Rules Glossary"
        # and "Player or DM?" are both page 7).
        ordering = ["chapter_id", "id"]

    def __str__(self) -> str:
        return self.name
