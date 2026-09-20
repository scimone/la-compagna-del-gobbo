"""Whole-character validation: what is still missing or wrong, per wizard step.

Structured (`Issue`: step / code / message / path) so a screen can put each message next to the
field it is about, and the Review step can list everything outstanding.
"""

from django.utils.translation import gettext as _

from . import abilities, class_choices, origins
from .store import STEPS, Draft, Issue

#: Steps that can't be answered before others have been - shown "locked" until then.
PREREQUISITES = {
    "equipment": ("class", "background"),
    "abilities": ("background",),
}


def _chosen(draft: Draft, step: str) -> bool:
    return {
        "class": draft.klass is not None,
        "background": draft.background is not None,
        "species": draft.species is not None,
    }.get(step, True)


def locked(draft: Draft, step: str) -> bool:
    return not all(_chosen(draft, needed) for needed in PREREQUISITES.get(step, ()))


def step_issues(draft: Draft) -> dict[str, list[Issue]]:
    """Issues for every step; a locked step reports none (there is nothing to fix yet)."""
    result: dict[str, list[Issue]] = {step: [] for step in STEPS}
    if draft.klass is None:
        result["class"] = [Issue("class", "missing", _("Choose a class."), "class")]
    else:
        result["class"] = class_choices.issues(draft)
    result["background"] = origins.background_issues(draft)
    result["species"] = origins.species_issues(draft)
    result["languages"] = origins.languages_issues(draft)
    if not locked(draft, "equipment"):
        result["equipment"] = origins.equipment_issues(draft)
    if not locked(draft, "abilities"):
        result["abilities"] = abilities.issues(draft)
    result["alignment"] = origins.alignment_issues(draft)
    result["review"] = abilities.manual_issues(draft.get("manual.abilities") or {})
    return result


def validate(draft: Draft) -> list[Issue]:
    return [issue for issues in step_issues(draft).values() for issue in issues]


def warnings(draft: Draft) -> list[Issue]:
    """Things worth showing that don't block finishing (an evil alignment)."""
    return origins.alignment_warnings(draft)
