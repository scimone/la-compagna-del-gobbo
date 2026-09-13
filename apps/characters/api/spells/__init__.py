from ninja import Router

router = Router(tags=["Character Spells"])

from . import (
    add_character_spell,
    list_character_spells,
    prepare_character_spell,
    remove_character_spell,
    unprepare_character_spell,
)
