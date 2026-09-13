"""Placeholder for GET /features/{feature_id}/effects."""

from apps.rules.api.rules import router


@router.get("/features/{feature_id}/effects")
def list_feature_effects(request, feature_id: int):
    """List the literal inline-tag effects found in a feature's text. TODO: implement."""
