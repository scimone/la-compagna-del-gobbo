"""SRD step 3: generate the six scores, assign them, add the background bonus.

Three methods (`standard` array, `roll` 4d6-drop-lowest, `pointbuy` 27 points), then the
background's +2/+1 or +1/+1/+1 (never above 20). The roll happens once per character and is
stored (D7): refreshing the page or going back never re-rolls.
"""

import secrets
from collections import Counter

from django.utils.translation import gettext as _

from apps.characters.models import Character

from .. import tables
from ..resolvers import abilities as ability_resolver
from . import effects
from .store import Draft, Issue, set_choice

STEP = "abilities"
METHODS = ("standard", "roll", "pointbuy")
_rng = secrets.SystemRandom()


def roll_four_d6_drop_lowest() -> tuple[int, list[int]]:
    dice = [_rng.randint(1, 6) for _ in range(4)]
    return sum(dice) - min(dice), dice


def roll_scores(character: Character) -> list[int]:
    """Six rolled totals. Rolled once and stored; later calls return the same six."""
    state = dict(Draft(character).get("abilities") or {})
    if not state.get("rolled"):
        rolls = [roll_four_d6_drop_lowest() for _ in range(6)]
        state["rolled"] = [total for total, _dice in rolls]
        state["rolls"] = [dice for _total, dice in rolls]
        set_choice(character, "abilities", state)
    return state["rolled"]


def bonus_rules(draft: Draft) -> tuple[list[str], list[tuple[int, ...]]]:
    """`(abilities the background may raise, allowed spreads)` from `Background.ability_scores`."""
    allowed: list[str] = []
    spreads: list[tuple[int, ...]] = []
    for option in draft.background.ability_scores if draft.background else []:
        weighted = option.get("choose", {}).get("weighted", {})
        allowed = weighted.get("from", allowed)
        spreads.append(tuple(sorted(weighted.get("weights", []), reverse=True)))
    return allowed, spreads


def issues(draft: Draft) -> list[Issue]:
    state = draft.get("abilities") or {}
    found: list[Issue] = []
    method, base = state.get("method"), state.get("base") or {}
    if method not in METHODS:
        return [
            Issue(
                STEP, "missing_method", _("Choose how to generate your ability scores."), "method"
            )
        ]
    if set(base) != set(tables.ABILITIES):
        return [Issue(STEP, "unassigned", _("Assign a score to every ability."), "base")]
    scores = [int(base[a]) for a in tables.ABILITIES]

    if method == "standard" and Counter(scores) != Counter(tables.STANDARD_ARRAY):
        found.append(
            Issue(
                STEP,
                "not_standard_array",
                _("Use each number of the standard array exactly once."),
                "base",
            )
        )
    elif method == "roll":
        if Counter(scores) != Counter(state.get("rolled", [])):
            found.append(Issue(STEP, "not_rolled", _("Assign the six numbers you rolled."), "base"))
    elif method == "pointbuy":
        if any(s not in tables.POINT_BUY_COST for s in scores):
            found.append(
                Issue(STEP, "point_buy_range", _("Point buy scores go from 8 to 15."), "base")
            )
        elif (
            tables.point_buy_cost(dict(zip(tables.ABILITIES, scores, strict=True)))
            > tables.POINT_BUY_BUDGET
        ):
            found.append(
                Issue(STEP, "point_buy_budget", _("You spent more than 27 points."), "base")
            )

    allowed, spreads = bonus_rules(draft)
    bonus = {a: int(v) for a, v in (state.get("bonus") or {}).items() if int(v)}
    if not bonus:
        found.append(
            Issue(
                STEP,
                "missing_bonus",
                _("Choose how your background raises your abilities."),
                "bonus",
            )
        )
    elif (
        not set(bonus) <= set(allowed) or tuple(sorted(bonus.values(), reverse=True)) not in spreads
    ):
        found.append(
            Issue(
                STEP,
                "bad_bonus",
                _("Raise abilities your background lists: +2 and +1, or +1 to three."),
                "bonus",
            )
        )
    if any(int(base[a]) + bonus.get(a, 0) > tables.CREATION_SCORE_CAP for a in tables.ABILITIES):
        found.append(Issue(STEP, "over_cap", _("An ability score can't go above 20."), "bonus"))
    return found


def save(
    character: Character, *, method: str, base: dict[str, int], bonus: dict[str, int]
) -> list[Issue]:
    """Store the assignment. Saved only if valid; returns the problems otherwise."""
    state = dict(Draft(character).get("abilities") or {})
    state |= {
        "method": method,
        "base": {a: int(v) for a, v in base.items()},
        "bonus": {a: int(v) for a, v in bonus.items() if int(v)},
    }
    set_choice(character, "abilities", state)
    problems = issues(Draft(character))
    effects.apply(character)
    return problems


def set_method(character: Character, method: str) -> None:
    """Switch generation method. The old assignment is dropped (its numbers came from the old
    method); the stored roll and the background bonus are kept."""
    if method not in METHODS:
        return
    state = dict(Draft(character).get("abilities") or {})
    if state.get("method") != method:
        state.pop("base", None)
    state["method"] = method
    set_choice(character, "abilities", state)
    effects.apply(character)


def suggest_standard_array(character: Character) -> None:
    """Assign the standard array the way the SRD suggests for the character's class."""
    draft = Draft(character)
    state = dict(draft.get("abilities") or {})
    state |= {"method": "standard", "base": dict(tables.STANDARD_ARRAY_BY_CLASS[draft.klass.id])}
    set_choice(character, "abilities", state)
    effects.apply(character)


def manual_issues(scores: dict) -> list[Issue]:
    low, high = tables.MANUAL_SCORE_RANGE
    return [
        Issue(
            "review",
            "manual_range",
            _("Ability scores go from %(low)d to %(high)d.") % {"low": low, "high": high},
            f"manual.abilities.{a}",
        )
        for a, v in scores.items()
        if a not in tables.ABILITIES or not low <= int(v) <= high
    ]


def options(draft: Draft) -> dict:
    allowed, spreads = bonus_rules(draft)
    state = draft.get("abilities") or {}
    return {
        "methods": METHODS,
        "standard_array": tables.STANDARD_ARRAY,
        "suggested": tables.STANDARD_ARRAY_BY_CLASS.get(draft.klass.id) if draft.klass else None,
        "rolled": state.get("rolled"),
        "point_buy_costs": tables.POINT_BUY_COST,
        "point_buy_budget": tables.POINT_BUY_BUDGET,
        "bonus_from": allowed,
        "bonus_spreads": spreads,
        "final": ability_resolver.final_scores(draft),
    }
