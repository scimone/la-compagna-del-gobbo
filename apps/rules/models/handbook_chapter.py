from django.db import models


class HandbookChapter(models.Model):
    """A top-level chapter of the handbook ("Playing the Game", "Character Origins", "Feats",
    "Equipment", "Spells"), sourced from the level-1 items of db/handbook.json's `data`.

    A chapter is only the heading its `HandbookSection` rows are grouped under - the Handbook menu
    shows it as a toggle heading above the buttons of its sections - so it holds nothing but its
    name. A chapter's own leading text (the "Playing the Game" intro narrative, which has no
    Italian translation) is not imported, see `apps/rules/handbook_source.py`.

    `name` is translated (`name_en`/`name_it`; see `apps/rules/translation.py`).
    """

    id = models.SlugField(primary_key=True, max_length=100)
    name = models.CharField(max_length=200)

    class Meta:
        # Same reasoning as `HandbookSection`: the source assigns ids in document order.
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name
