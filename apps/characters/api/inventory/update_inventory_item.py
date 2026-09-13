from apps.characters.api.inventory import router
from apps.characters.schemas import (
    CharacterInventoryItemSchema,
    CharacterInventoryItemUpdateSchema,
)
from apps.characters.services import inventory


@router.patch("/{character_id}/inventory/{item_id}", response=CharacterInventoryItemSchema)
def update_inventory_item(
    request, character_id: int, item_id: int, payload: CharacterInventoryItemUpdateSchema
):
    return inventory.update_inventory_item(
        character_id, item_id, **payload.dict(exclude_unset=True, by_alias=True)
    )
