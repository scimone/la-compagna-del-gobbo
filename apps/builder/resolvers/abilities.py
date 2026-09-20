"""Ability scores: base allocation + background bonus, then the manual override.

`final_scores` is the one place that says what a draft's six scores are; the wizard screens, the
hit-point calculation and `effects.apply()` all read it.
"""

from apps.builder.tables import ABILITIES, ability_modifier

from ..services.store import Draft

DEFAULT_SCORE = 10


def base_scores(draft: Draft) -> dict[str, int]:
    base = (draft.get("abilities") or {}).get("base") or {}
    return {a: int(base.get(a, DEFAULT_SCORE)) for a in ABILITIES}


def bonus_scores(draft: Draft) -> dict[str, int]:
    bonus = (draft.get("abilities") or {}).get("bonus") or {}
    return {a: int(bonus.get(a, 0)) for a in ABILITIES}


def generated_scores(draft: Draft) -> dict[str, int]:
    """Base + background bonus - what the rules give, before any manual edit."""
    base, bonus = base_scores(draft), bonus_scores(draft)
    return {a: base[a] + bonus[a] for a in ABILITIES}


def manual_scores(draft: Draft) -> dict[str, int]:
    return {a: int(v) for a, v in (draft.get("manual.abilities") or {}).items() if a in ABILITIES}


def final_scores(draft: Draft) -> dict[str, int]:
    """The character's scores. A manual override wins over everything (class, species and
    background included): the player can set any score at the end of creation."""
    return {**generated_scores(draft), **manual_scores(draft)}


def modifiers(draft: Draft) -> dict[str, int]:
    return {a: ability_modifier(s) for a, s in final_scores(draft).items()}
