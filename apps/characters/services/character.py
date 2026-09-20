"""Character CRUD and the resolved character sheet (create_character, get_character, ...)."""

from django.shortcuts import get_object_or_404

from apps.characters.models import (
    Character,
    CharacterAbilityScoreIncrease,
    CharacterClass,
    CharacterCurrency,
    CharacterFeat,
    CharacterFeature,
    CharacterInventoryItem,
    CharacterLanguage,
    CharacterOptionalFeature,
    CharacterProficiency,
    CharacterResource,
    CharacterSense,
    CharacterSpell,
)


def list_characters():
    """Finished characters. A draft still being built by the creation wizard isn't a character
    yet (and belongs to its owner alone), so it is left out."""
    return Character.objects.filter(status=Character.STATUS_COMPLETE)


def create_character(**data) -> Character:
    return Character.objects.create(**data)


def get_character(character_id: int) -> Character:
    return get_object_or_404(Character, pk=character_id)


def update_character(character_id: int, **data) -> Character:
    character = get_character(character_id)
    for field, value in data.items():
        setattr(character, field, value)
    character.save()
    return character


def delete_character(character_id: int) -> None:
    get_character(character_id).delete()


def get_character_sheet(character_id: int) -> dict:
    character = get_character(character_id)
    return {
        "character": character,
        "classes": CharacterClass.objects.filter(character=character),
        "ability_score_increases": CharacterAbilityScoreIncrease.objects.filter(
            character=character
        ),
        "features": CharacterFeature.objects.filter(character=character),
        "feats": CharacterFeat.objects.filter(character=character),
        "optional_features": CharacterOptionalFeature.objects.filter(character=character),
        "languages": CharacterLanguage.objects.filter(character=character),
        "proficiencies": CharacterProficiency.objects.filter(character=character),
        "senses": CharacterSense.objects.filter(character=character),
        "inventory_items": CharacterInventoryItem.objects.filter(character=character),
        "currency": CharacterCurrency.objects.filter(character=character).first(),
        "spells": CharacterSpell.objects.filter(character=character),
        "resources": CharacterResource.objects.filter(character=character),
    }
