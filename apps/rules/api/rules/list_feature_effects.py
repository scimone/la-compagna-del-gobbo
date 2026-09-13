from apps.rules.api.rules import router
from apps.rules.schemas import EffectSchema
from apps.rules.services import feature


@router.get("/features/{feature_id}/effects", response=list[EffectSchema])
def list_feature_effects(request, feature_id: int):
    return feature.list_feature_effects(feature_id)
