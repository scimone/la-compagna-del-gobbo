"""Which skills and tools a draft's character already has, and from where.

D6 in `docs/character_creation_plan.md`: a later picker never offers what the character already
has. That needs a per-source view - "everything held *except* what this picker itself chose" - so
a source can be re-picked without its own previous answer blocking it.

Source keys: `background` (fixed skills, tool, tool pick), `background.feat`, `species`,
`species.feat`, `class`.
"""

from apps.rules.models import Skill

from ..services.store import Draft
from .proficiency import background_tool_grant, named_tool_ids


def _feat_holdings(chosen: dict | None) -> tuple[set[str], set[str]]:
    skills: set[str] = set()
    tools: set[str] = set(chosen.get("tools", [])) if chosen else set()
    for value in (chosen or {}).get("proficiencies", []):
        kind, _, name = value.partition(":")
        (skills if kind == "skill" else tools).add(name)
    return skills, tools


def sources(draft: Draft) -> dict[str, dict[str, set[str]]]:
    held: dict[str, dict[str, set[str]]] = {}
    if draft.background:
        fixed_tools, _pick = background_tool_grant(draft.background)
        picked = draft.get("background.tool")
        held["background"] = {
            "skills": {s.id for s in draft.background.skills.all()},
            "tools": {*fixed_tools, *([picked] if picked else [])},
        }
        skills, tools = _feat_holdings(draft.get("background.feat"))
        held["background.feat"] = {"skills": skills, "tools": tools}
    if draft.species:
        skill = draft.get("species.skill")
        held["species"] = {"skills": {skill} if skill else set(), "tools": set()}
        skills, tools = _feat_holdings(draft.get("species.feat"))
        held["species.feat"] = {"skills": skills, "tools": tools}
    if draft.klass:
        held["class"] = {
            "skills": set(draft.get("class.skills", [])),
            "tools": {
                *named_tool_ids(draft.klass.tool_proficiencies),
                *draft.get("class.tools", []),
            },
        }
    return held


def held(draft: Draft, *, exclude: tuple[str, ...] = ()) -> dict[str, set[str]]:
    """`{"skills": {...}, "tools": {...}}` held from every source not in `exclude`."""
    result: dict[str, set[str]] = {"skills": set(), "tools": set()}
    for source, holdings in sources(draft).items():
        if source not in exclude:
            result["skills"] |= holdings["skills"]
            result["tools"] |= holdings["tools"]
    return result


def duplicates(draft: Draft) -> list[tuple[str, str, list[str]]]:
    """`(kind, id, [sources])` for a skill/tool granted by more than one source."""
    seen: dict[tuple[str, str], list[str]] = {}
    for source, holdings in sources(draft).items():
        for kind in ("skills", "tools"):
            for ident in holdings[kind]:
                seen.setdefault((kind, ident), []).append(source)
    return [(kind, ident, srcs) for (kind, ident), srcs in seen.items() if len(srcs) > 1]


def all_skill_ids() -> set[str]:
    return set(Skill.objects.values_list("id", flat=True))
