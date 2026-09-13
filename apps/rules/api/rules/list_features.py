from apps.rules.api.rules import router
from apps.rules.schemas import FeatureSchema
from apps.rules.services import feature


@router.get("/features", response=list[FeatureSchema])
def list_features(request):
    return feature.list_features()
