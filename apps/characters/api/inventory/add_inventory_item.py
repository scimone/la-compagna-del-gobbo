from apps.characters.api.inventory import router
from apps.characters.schemas import (
    CharacterInventoryItemCreateSchema,
    CharacterInventoryItemSchema,
)
from apps.characters.services import inventory


@router.post("/{character_id}/inventory", response=CharacterInventoryItemSchema)
def add_inventory_item(request, character_id: int, payload: CharacterInventoryItemCreateSchema):
    return inventory.add_inventory_item(character_id, **payload.dict(by_alias=True))
