from apps.rules.api.rules import router
from apps.rules.schemas import OptionalFeatureSchema
from apps.rules.services import optional_feature


@router.get("/optional-features", response=list[OptionalFeatureSchema])
def list_optional_features(request):
    return optional_feature.list_optional_features()
