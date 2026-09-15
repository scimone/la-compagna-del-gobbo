from django.db import models


class HandbookSection(models.Model):
    """A named top-level topic of the handbook, sourced from db/handbook.json.

    There's only ever one chapter in db/handbook.json ("Chapter 1: Playing the Game"), so this
    doesn't model chapters as their own grouping - it flattens one level instead: the chapter's
    own root block becomes one row (its `entries` being just its own leading content - the
    intro narrative - not the nested sections' content too), and each of its direct named
    children ("Rules Glossary", "Player or DM?", "Dice", ... - a mix of the source's `section`
    and `inset` types, both treated the same here) becomes one more row. If a second chapter is
    ever added to the source, this flattening still works the same way per chapter; there's just
    no `HandbookChapter`-style parent to group rows by chapter today, since there's nothing to
    group.
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)
    page = models.PositiveSmallIntegerField()
    entries = models.JSONField(default=list, blank=True)

    class Meta:
        # `id` (e.g. "008", "009", "00c", ...) is a same-length hex-ish code assigned in document
        # order by the source, so sorting by it (as a plain string) reproduces reading order -
        # `page` alone has ties (e.g. "Rules Glossary" and "Player or DM?" are both page 7).
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name
