"""Placeholder for GET /features/{feature_id}."""

from apps.rules.api.rules import router


@router.get("/features/{feature_id}")
def get_feature(request, feature_id: int):
    """Retrieve a feature. TODO: implement via services."""
