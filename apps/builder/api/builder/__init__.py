from ninja import Router

router = Router(tags=["Character Builder"])

from . import (
    choose_starting_equipment,
    finalize_character,
    get_builder_choice,
    get_builder_state,
    list_ability_score_options,
    list_builder_choices,
    list_starting_equipment_options,
    select_background,
    select_class,
    select_species,
    set_ability_scores,
    set_builder_choice,
)
