"""Known/prepared spell management for a character."""

from django.shortcuts import get_object_or_404

from apps.characters.models import CharacterSpell
from apps.characters.services.character import get_character


def list_character_spells(character_id: int):
    get_character(character_id)
    return CharacterSpell.objects.filter(character_id=character_id)


def add_character_spell(character_id: int, **data) -> CharacterSpell:
    character = get_character(character_id)
    return CharacterSpell.objects.create(character=character, **data)


def _get_character_spell(character_id: int, spell_id: str) -> CharacterSpell:
    get_character(character_id)
    return get_object_or_404(CharacterSpell, character_id=character_id, spell_id=spell_id)


def remove_character_spell(character_id: int, spell_id: str) -> None:
    _get_character_spell(character_id, spell_id).delete()


def prepare_character_spell(character_id: int, spell_id: str) -> CharacterSpell:
    character_spell = _get_character_spell(character_id, spell_id)
    character_spell.prepared = True
    character_spell.save(update_fields=["prepared"])
    return character_spell


def unprepare_character_spell(character_id: int, spell_id: str) -> CharacterSpell:
    character_spell = _get_character_spell(character_id, spell_id)
    character_spell.prepared = False
    character_spell.save(update_fields=["prepared"])
    return character_spell
