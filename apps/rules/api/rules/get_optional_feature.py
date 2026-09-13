"""Placeholder for GET /optional-features/{optional_feature_id}."""

from apps.rules.api.rules import router


@router.get("/optional-features/{optional_feature_id}")
def get_optional_feature(request, optional_feature_id: str):
    """Retrieve an optional class feature. TODO: implement via services."""
