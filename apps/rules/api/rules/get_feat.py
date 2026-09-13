"""Placeholder for GET /feats/{feat_id}."""

from apps.rules.api.rules import router


@router.get("/feats/{feat_id}")
def get_feat(request, feat_id: int):
    """Retrieve a feat. TODO: implement via services."""
