"""What the chosen background gives a level-1 character (SRD step 2)."""

from ..services.store import Draft
from . import feat as feat_resolver
from .grants import Grants
from .proficiency import background_tool_grant


def background_grants(draft: Draft, grants: Grants) -> None:
    background = draft.background
    if background is None:
        return
    for skill in background.skills.all():
        grants.add_proficiency("skill", skill.id)
    fixed_tools, _pick = background_tool_grant(background)
    for tool_id in [
        *fixed_tools,
        *([draft.get("background.tool")] if draft.get("background.tool") else []),
    ]:
        grants.add_proficiency("tool", tool_id)
    if background.feat:
        chosen = dict(draft.get("background.feat") or {})
        feat_resolver.apply_feat(
            grants, background.feat, chosen, "background", variant=background.feat_variant
        )
