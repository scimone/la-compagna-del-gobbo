from ninja import Router

from apps.characters.api.characters import router as characters_router
from apps.characters.api.details import router as details_router
from apps.characters.api.inventory import router as inventory_router
from apps.characters.api.spells import router as spells_router

router = Router()
router.add_router("", characters_router)
router.add_router("", inventory_router)
router.add_router("", spells_router)
router.add_router("", details_router)
