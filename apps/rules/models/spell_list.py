from django.db import models


class SpellList(models.Model):
    """The list of spells available to a given Class.

    Not populated from db/: there is no separate spell-list catalog - each `Spell` already
    carries its own `classes`/`subclasses` list (see `rules.Spell`). TODO: decide whether a
    dedicated SpellList model/table adds anything beyond querying Spell by class, or drop this
    placeholder.
    """

    def __str__(self) -> str:
        return f"SpellList #{self.pk}"
