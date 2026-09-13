from apps.rules.api.rules import router
from apps.rules.schemas import BackgroundSchema
from apps.rules.services import background


@router.get("/backgrounds", response=list[BackgroundSchema])
def list_backgrounds(request):
    return background.list_backgrounds()
