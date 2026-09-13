from apps.rules.api.rules import router
from apps.rules.schemas import FeatSchema
from apps.rules.services import feat


@router.get("/feats/{feat_id}", response=FeatSchema)
def get_feat(request, feat_id: str):
    return feat.get_feat(feat_id)
