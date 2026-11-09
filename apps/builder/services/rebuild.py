"""Rebuilding a levelled character (an admin changing its species, class, ... above level 1).

The creation wizard recomputes a character from its level-1 choices, whereas a level-up is written
straight to the rows (`progression.commit`). So a character above level 1 is rebuilt in two phases:

1. `begin()` takes it back to a level-1 draft - the level-up leftovers (extra classes, subclass,
   level-up choices, the rest windows) are removed and the recorded level-ups are set aside as
   `pending` - and the wizard changes whatever the admin wants. Everything that was connected to a
   changed component is simply regenerated from the new choices.
2. `creation.finalize()` then calls `start_replay()`, and `advance()` re-applies the recorded
   levels one by one. A level whose recorded picks are still valid is applied as it was; a level
   that is not (its class was swapped, a species/background change closed a pick, a new pick
   opened) stops and is asked again, on the level-up page, with what is still valid filled in.
   When no level is pending the character is complete again.

Every `progression.commit()` appends its class and picks to `meta.history`; a character levelled
before that existed has its levels reconstructed from its class rows, with no picks recorded (so
each of them is asked).
"""

from collections import Counter

from django.core.exceptions import ObjectDoesNotExist

from apps.characters.models import Character, CharacterChoice

from ..class_spec import spec_for
from .store import (
    EDITING_KEY,
    HISTORY_KEY,
    REBUILD_KEY,
    WIZARD_PREFIXES,
    Draft,
    clear_choices,
    set_choice,
)


def _stored(character: Character, key: str):
    row = CharacterChoice.objects.filter(character=character, key=key).first()
    return row.value if row else None


# --- the recorded levels ----------------------------------------------------------------------


def record(character: Character, class_id: str, values) -> None:
    """Note one applied level-up (called by `progression.commit`)."""
    entries = list(_stored(character, HISTORY_KEY) or [])
    entries.append({"klass": class_id, "values": {k: list(v) for k, v in values.items()}})
    set_choice(character, HISTORY_KEY, entries)


def _from_rows(character: Character) -> list[dict]:
    """The levels above the first, from the class rows alone: the starting class first, then each
    other class in the order it was taken. No picks are known."""
    entries: list[dict] = []
    for row in character.classes.order_by("-is_starting_class", "pk"):
        extra = row.level - 1 if row.is_starting_class else row.level
        entries += [{"klass": row.klass_id, "values": {}} for _ in range(extra)]
    return entries


def history(character: Character) -> list[dict]:
    """The character's levels above the first, in order: the recorded ones when they agree with the
    class rows, else rebuilt from the rows."""
    rows = _from_rows(character)
    stored = _stored(character, HISTORY_KEY) or []
    if Counter(e["klass"] for e in stored) == Counter(e["klass"] for e in rows):
        return stored
    return rows


# --- phase 1: back to level 1 ----------------------------------------------------------------


def total_level(character: Character) -> int:
    return sum(character.classes.values_list("level", flat=True)) or 1


def begin(character: Character) -> None:
    """Take a finished character above level 1 back to a level-1 draft (inventory, coins and
    Experience Points stay). The level-ups are kept in `meta.rebuild` to be replayed."""
    pending = history(character)
    start = character.classes.filter(is_starting_class=True).select_related("klass").first()
    set_choice(
        character,
        REBUILD_KEY,
        {"pending": pending, "start": start.klass_id if start else "", "replaying": False},
    )
    CharacterChoice.objects.filter(character=character).exclude(
        key__regex="^(" + "|".join(p.replace(".", r"\.") for p in WIZARD_PREFIXES) + ")"
    ).delete()
    clear_choices(character, HISTORY_KEY)
    if start:
        # level-up picks were appended to the Weapon Mastery choice; the level-1 ones come first
        spec = spec_for(start.klass_id)
        row = CharacterChoice.objects.filter(
            character=character, key="class.weapon_mastery"
        ).first()
        if row and spec and spec.weapon_mastery:
            row.value = list(row.value)[: spec.weapon_mastery.count]
            row.save(update_fields=["value"])
        character.classes.exclude(pk=start.pk).delete()
        start.level, start.subclass, start.hit_dice_spent = 1, None, 0
        start.save()
    character.spell_changes = {}
    character.weapon_mastery_changes = {}
    character.rest_choices = {}
    character.save(update_fields=["spell_changes", "weapon_mastery_changes", "rest_choices"])


# --- phase 2: replaying the levels -------------------------------------------------------------


def _state(character: Character) -> dict | None:
    return _stored(character, REBUILD_KEY)


def pending(character: Character) -> list[dict]:
    return (_state(character) or {}).get("pending", [])


def has_pending(character: Character) -> bool:
    return bool(pending(character))


def replaying(character: Character) -> bool:
    """Whether the wizard part is over and the levels are being re-applied."""
    state = _state(character)
    return bool(state and state.get("replaying"))


def start_replay(character: Character) -> None:
    """The wizard is finished: if the starting class changed, its levels become levels of the new
    one (with nothing recorded, so each is asked)."""
    state = _state(character)
    draft = Draft(character)
    new_start = draft.klass.id if draft.klass else ""
    old_start = state["start"]
    if new_start != old_start:
        for entry in state["pending"]:
            if entry["klass"] == old_start:
                entry["klass"], entry["values"] = new_start, {}
        state["start"] = new_start
    state["replaying"] = True
    set_choice(character, REBUILD_KEY, state)


def progress(character: Character) -> tuple[int, int]:
    """`(levels applied, levels to apply in all)` above level 1."""
    done = total_level(character) - 1
    return done, done + len(pending(character))


def advance(character: Character) -> dict | None:
    """Re-apply the recorded levels that are still valid, in order. Returns the first one that
    needs the admin's decision, or `None` once every level is back (the character is complete)."""
    from . import progression  # local: progression records into this module

    while entries := pending(character):
        entry = entries[0]
        try:
            progression.commit(character, entry["klass"], entry["values"], rebuilding=True)
        except (ValueError, LookupError, ObjectDoesNotExist):
            return entry
        drop_first(character)
    complete(character)
    return None


def drop_first(character: Character) -> None:
    state = _state(character)
    state["pending"] = state["pending"][1:]
    set_choice(character, REBUILD_KEY, state)


def complete(character: Character) -> None:
    clear_choices(character, REBUILD_KEY, EDITING_KEY)
    character.status = Character.STATUS_COMPLETE
    character.save(update_fields=["status", "updated_at"])
