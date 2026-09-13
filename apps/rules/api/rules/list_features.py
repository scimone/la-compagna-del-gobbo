"""Placeholder for GET /features."""

from apps.rules.api.rules import router


@router.get("/features")
def list_features(request):
    """List all features. TODO: implement via services."""
