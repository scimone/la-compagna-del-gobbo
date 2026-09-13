from ninja import Router

router = Router(tags=["Character Inventory"])

from . import (
    add_inventory_item,
    delete_inventory_item,
    equip_inventory_item,
    get_currency,
    list_inventory,
    unequip_inventory_item,
    update_currency,
    update_inventory_item,
)
