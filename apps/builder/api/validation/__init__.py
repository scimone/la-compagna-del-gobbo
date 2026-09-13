from ninja import Router

router = Router(tags=["Character Validation"])

from . import get_builder_validation, validate_character
