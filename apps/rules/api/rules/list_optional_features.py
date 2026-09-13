"""Placeholder for GET /optional-features."""

from apps.rules.api.rules import router


@router.get("/optional-features")
def list_optional_features(request):
    """List all optional class features. TODO: implement via services."""
