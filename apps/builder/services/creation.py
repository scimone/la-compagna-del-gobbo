"""The creation wizard's lifecycle: start a draft, report progress, finish (or discard) it."""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.characters.models import Character, CharacterCurrency

from .. import tables
from . import effects, validation
from .store import STEPS, Draft, Issue, clear_choices, set_choice

#: Steps that must be complete before Finish (`details` is optional, `review` is derived).
REQUIRED_STEPS = tuple(s for s in STEPS if s not in ("details", "review"))


def start_draft(owner, name: str) -> Character:
    character = Character.objects.create(
        name=name.strip()[:100] or _("New character"),
        owner=owner if getattr(owner, "is_authenticated", False) else None,
        status=Character.STATUS_DRAFT,
    )
    CharacterCurrency.objects.create(character=character)
    return character


def get_state(character: Character) -> dict:
    """Progress for the wizard: one entry per step (`complete` / `incomplete` / `locked`), the step
    to show next, whether the character can be finished, and non-blocking warnings."""
    draft = Draft(character)
    by_step = validation.step_issues(draft)
    steps = []
    for step in STEPS:
        if validation.locked(draft, step):
            status = "locked"
        elif by_step[step]:
            status = "incomplete"
        elif step in ("details", "review"):
            status = "optional"
        else:
            status = "complete"
        steps.append(
            {"key": step, "status": status, "issues": [i.as_dict() for i in by_step[step]]}
        )
    current = next((s["key"] for s in steps if s["status"] == "incomplete"), "review")
    ready = (
        all(s["status"] == "complete" for s in steps if s["key"] in REQUIRED_STEPS)
        and not by_step["review"]
    )
    return {
        "steps": steps,
        "current": current,
        "ready": ready,
        "warnings": [w.as_dict() for w in validation.warnings(draft)],
    }


# --- details & the manual layer ---------------------------------------------------------------


def save_details(
    character: Character, *, appearance: str = "", notes: str = "", backstory: dict | None = None
) -> None:
    character.appearance = appearance
    character.notes = notes
    character.save(update_fields=["appearance", "notes", "updated_at"])
    details = dict(Draft(character).get("details") or {})
    if backstory is not None:
        details["backstory"] = backstory
    set_choice(character, "details", details)


def set_manual_abilities(character: Character, scores: dict[str, int]) -> list[Issue]:
    """Override any ability scores by hand (1-30), whatever class/species/background say. Passing
    a score equal to the generated one is the same as not overriding it."""
    from . import abilities

    problems = abilities.manual_issues(scores)
    if problems:
        return problems
    generated = _generated(character)
    manual = {a: int(v) for a, v in scores.items() if int(v) != generated[a]}
    set_choice(character, "manual.abilities", manual)
    effects.apply(character)
    return []


def _generated(character: Character) -> dict[str, int]:
    from ..resolvers import abilities as ability_resolver

    return ability_resolver.generated_scores(Draft(character))


def set_manual_skills(character: Character, states: dict[str, str]) -> list[Issue]:
    """Override any skill's state by hand: `"none"`, `"proficient"` or `"expertise"`."""
    from apps.rules.models import Skill

    valid = set(Skill.objects.values_list("id", flat=True))
    bad = [
        s
        for s, state in states.items()
        if s not in valid or state not in ("none", "proficient", "expertise")
    ]
    if bad:
        return [
            Issue("review", "manual_skill", _("Unknown skill or state."), f"manual.skills.{s}")
            for s in bad
        ]
    set_choice(character, "manual.skills", dict(states))
    effects.apply(character)
    return []


def reset_manual(character: Character) -> None:
    clear_choices(character, "manual.")
    effects.apply(character)


# --- finishing ---------------------------------------------------------------------------------


@transaction.atomic
def finalize(character: Character) -> list[Issue]:
    """Make the character real. Refuses (returning why) until every required step is complete."""
    if character.status != Character.STATUS_DRAFT:
        return []
    state = get_state(character)
    if not state["ready"]:
        return validation.validate(Draft(character)) or [
            Issue("review", "incomplete", _("Finish every step first."))
        ]
    effects.apply(character)  # one last recompute from the final choices
    character.status = Character.STATUS_COMPLETE
    character.experience_points = tables.xp_for_level(Draft(character).level)
    character.save(update_fields=["status", "experience_points", "updated_at"])
    return []


def discard(character: Character) -> None:
    """Delete a draft. A finished character is never deleted through the wizard."""
    if character.status == Character.STATUS_DRAFT:
        character.delete()
