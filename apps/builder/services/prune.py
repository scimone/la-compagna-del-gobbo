"""Drop picks that an earlier answer has made impossible.

The wizard lets the player answer in any order (the class and its choices come first, the
background and species after), so a later answer can invalidate an earlier pick: a background that
already grants Athletics makes Athletics an impossible class-skill pick (no duplicate
proficiencies, D6), a different background changes which spell list Magic Initiate offers, a
different lineage changes the cantrip list. Such a pick is removed here rather than kept, so it
can never turn into a grant, and the step shows the choice as still to do.

Only *invalid* values are removed; a valid selection - even an incomplete one - is left alone.
"""

from apps.characters.models import Character

from . import class_choices, origins
from .store import Draft, store_picker

_MAX_ROUNDS = 3  # a removal can invalidate a dependent picker (spellbook -> prepared spells)


def all_pickers(draft: Draft):
    return [
        *class_choices.pickers(draft),
        *origins.background_pickers(draft),
        *origins.species_pickers(draft),
    ]


def run(character: Character) -> bool:
    """Prune until stable. Returns whether anything was removed."""
    removed = False
    for _round in range(_MAX_ROUNDS):
        changed = False
        for picker in all_pickers(Draft(character)):
            valid = [v for v in picker.selected if v in picker.candidate_ids]
            if len(valid) != len(picker.selected):
                store_picker(
                    character, picker.key, (valid[0] if valid else "") if picker.single else valid
                )
                changed = removed = True
        if not changed:
            break
    return removed
