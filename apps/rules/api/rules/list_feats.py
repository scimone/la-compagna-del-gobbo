"""Placeholder for GET /feats."""

from apps.rules.api.rules import router


@router.get("/feats")
def list_feats(request):
    """List all feats. TODO: implement via services."""
