"""The creation wizard's lifecycle: start a draft, report progress, finish (or discard) it."""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.characters.models import Character, CharacterCurrency

from .. import tables
from . import effects, validation
from .store import EDITING_KEY, STEPS, Draft, Issue, clear_choices, set_choice

#: Steps that must be complete before Finish (`details` is optional, `review` is derived).
REQUIRED_STEPS = tuple(s for s in STEPS if s not in ("story", "review"))


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
        elif step in ("story", "review"):
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


def save_backstory(character: Character, text: str) -> None:
    """The background story: one free-form text (the SRD's questions are just a guide)."""
    character.backstory = text.strip()
    character.save(update_fields=["backstory", "updated_at"])


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
    # Only what differs from what the rules give is an override; an untouched skill keeps
    # following the background/class/species if those change later.
    generated = effects.compute_grants(Draft(character), manual=False).proficiencies
    overrides = {
        skill: state
        for skill, state in states.items()
        if state != generated.get(("skill", skill), "none")
    }
    set_choice(character, "manual.skills", overrides)
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
    if is_editing(character):
        clear_choices(character, EDITING_KEY)
        character.save(update_fields=["status", "updated_at"])
        return []
    character.experience_points = tables.xp_for_level(Draft(character).level)
    character.save(update_fields=["status", "experience_points", "updated_at"])
    return []


def is_editing(character: Character) -> bool:
    """A finished character reopened in the wizard (see `reopen()`)."""
    return bool(Draft(character).get(EDITING_KEY))


def can_reopen(character: Character) -> bool:
    """Only a finished character that has not levelled up: the wizard recomputes a character from
    its level-1 choices, whereas a level-up is written straight to the rows and would be lost."""
    from .progression import total_level  # local: progression -> resolvers

    return character.status == Character.STATUS_COMPLETE and total_level(character) == 1


def reopen(character: Character) -> bool:
    """Turn a finished level-1 character back into a draft so the wizard can change it. Its
    inventory, coins and Experience Points are kept (see `effects.apply()`)."""
    if not can_reopen(character):
        return False
    set_choice(character, EDITING_KEY, True)
    character.status = Character.STATUS_DRAFT
    character.save(update_fields=["status", "updated_at"])
    return True


def discard(character: Character) -> None:
    """Delete a draft. A finished character is never deleted through the wizard, nor is one that
    is being edited."""
    if character.status == Character.STATUS_DRAFT and not is_editing(character):
        character.delete()
