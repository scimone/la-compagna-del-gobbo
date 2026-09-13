from apps.rules.api.rules import router
from apps.rules.schemas import OptionalFeatureSchema
from apps.rules.services import optional_feature


@router.get("/optional-features/{optional_feature_id}", response=OptionalFeatureSchema)
def get_optional_feature(request, optional_feature_id: str):
    return optional_feature.get_optional_feature(optional_feature_id)
