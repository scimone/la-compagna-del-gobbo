from ninja import Router

router = Router(tags=["Character Progression"])

from . import commit_level_up, get_level_up_info, preview_level_up
