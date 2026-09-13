from apps.rules.api.rules import router
from apps.rules.schemas import ChoiceDefinitionSchema
from apps.rules.services import background


@router.get("/backgrounds/{background_id}/choices", response=list[ChoiceDefinitionSchema])
def list_background_choices(request, background_id: str):
    return background.list_background_choices(background_id)
