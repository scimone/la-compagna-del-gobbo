"""Circle of the Land's land, chosen anew after every Long Rest.

The land picked when the subclass was chosen (`subclass.<class>.land` in `CharacterChoice`)
decides the Circle spells the Druid has prepared and which "Circle of the Land Spells (...)"
feature the character shows. A Long Rest opens the choice (`Character.rest_choices["land"]`, see
`play.grant_rest_choices()`); `change_land()` makes it.
"""

from django.db import transaction

from apps.characters.models import Character, CharacterChoice, CharacterClass, CharacterSpell

from ..resolvers.spell import spell_id
from .progression import _grant_land_feature, _refs, _subclass_spells


def _land_row(character: Character) -> tuple[CharacterClass, CharacterChoice] | None:
    for row in character.classes.select_related("subclass"):
        choice = CharacterChoice.objects.filter(
            character=character, key=f"subclass.{row.klass_id}.land"
        ).first()
        if row.subclass and choice:
            return row, choice
    return None


def land_options(character: Character) -> dict | None:
    """`{"current", "lands": [names]}` while the Long Rest's land choice is open, else None."""
    if not character.rest_choices.get("land"):
        return None
    found = _land_row(character)
    if not found:
        return None
    row, choice = found
    names = [e["name"] for e in row.subclass.additional_spells if e.get("name")]
    return {"current": choice.value, "lands": names}


def _land_spell_ids(subclass, land: str) -> set[str]:
    ids = set()
    for entry in subclass.additional_spells:
        if entry.get("name") != land:
            continue
        for block in ("prepared", "known", "innate"):
            for refs in (entry.get(block) or {}).values():
                ids.update(spell_id(ref) for ref in _refs(refs))
    return ids


@transaction.atomic
def change_land(character: Character, land: str) -> None:
    """Take `land` (the current one is fine) and close the choice: the previous land's Circle
    spells give way to the new land's, up to the Druid level, and so does its feature."""
    options = land_options(character)
    if options is None:
        raise ValueError("there is no land to choose now")
    if land not in options["lands"]:
        raise ValueError("unknown land")
    row, choice = _land_row(character)
    if land != choice.value:
        subclass = row.subclass
        CharacterSpell.objects.filter(
            character=character,
            source=f"subclass:{subclass.pk}",
            spell_id__in=_land_spell_ids(subclass, choice.value),
        ).delete()
        choice.value = land
        choice.save(update_fields=["value"])

        class _Ctx:  # the little `_subclass_spells()` needs
            pass

        ctx = _Ctx()
        ctx.character, ctx.klass = character, row.klass
        _subclass_spells(ctx, subclass, row.level, land)
        _grant_land_feature(character, subclass, land, row.level)
    rest_choices = dict(character.rest_choices)
    rest_choices.pop("land", None)
    character.rest_choices = rest_choices
    character.save(update_fields=["rest_choices"])
