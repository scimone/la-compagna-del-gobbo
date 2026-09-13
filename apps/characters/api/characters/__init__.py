from ninja import Router

router = Router(tags=["Characters"])

from . import (
    create_character,
    delete_character,
    get_character,
    get_character_sheet,
    list_characters,
    update_character,
)
