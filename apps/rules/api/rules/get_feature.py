from apps.rules.api.rules import router
from apps.rules.schemas import FeatureSchema
from apps.rules.services import feature


@router.get("/features/{feature_id}", response=FeatureSchema)
def get_feature(request, feature_id: int):
    return feature.get_feature(feature_id)
