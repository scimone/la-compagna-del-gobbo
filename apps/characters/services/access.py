"""Who may see and change a character (D1 in `docs/character_creation_plan.md`).

Every character is visible to every account; only its owner edits or deletes it. Later the owner
may want to hide certain sections of a character from other accounts, so every view asks
`can_view(user, character, section)` instead of assuming - that is the one place to change then.
"""

from apps.characters.models import Character


def can_view(user, character: Character, section: str = "") -> bool:
    """`section` names a part of the character page (`"inventory"`, `"notes"`, ...). Everyone may
    see everything for now, except that another account's *unfinished* character is not shown."""
    if character.status == Character.STATUS_DRAFT:
        return can_edit(user, character)
    return True


def can_edit(user, character: Character) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and character.owner_id == user.id
