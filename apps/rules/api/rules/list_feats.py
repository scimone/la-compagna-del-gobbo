from apps.rules.api.rules import router
from apps.rules.schemas import FeatSchema
from apps.rules.services import feat


@router.get("/feats", response=list[FeatSchema])
def list_feats(request):
    return feat.list_feats()
