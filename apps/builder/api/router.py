from ninja import Router

from apps.builder.api.builder import router as builder_router
from apps.builder.api.progression import router as progression_router
from apps.builder.api.validation import router as validation_router

router = Router()
router.add_router("", builder_router)
router.add_router("", validation_router)
router.add_router("", progression_router)
