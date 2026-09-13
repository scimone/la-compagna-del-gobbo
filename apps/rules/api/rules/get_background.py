from apps.rules.api.rules import router
from apps.rules.schemas import BackgroundSchema
from apps.rules.services import background


@router.get("/backgrounds/{background_id}", response=BackgroundSchema)
def get_background(request, background_id: str):
    return background.get_background(background_id)
