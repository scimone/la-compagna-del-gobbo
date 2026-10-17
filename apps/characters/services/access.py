"""Who may see and change a character.

A character belongs to one campaign (`Character.campaign`). Its members see every finished
character in it; the character's owner and the campaign's DM change it; administrators
(`settings.ADMIN_ACCOUNTS`) do everything everywhere. Someone who is not in the campaign gets a
404, as if the character did not exist. Later the owner may want to hide certain sections of a
character from other members, so every view asks `can_view(user, character, section)` instead of
assuming - that is the one place to change then.

Memberships themselves live in `apps.campaigns.services.membership`.
"""

from apps.campaigns.services import membership
from apps.characters.models import Character

is_admin = membership.is_admin


def is_dm(user, campaign) -> bool:
    """The Dungeon Master *of this campaign*."""
    return membership.is_dm(user, campaign)


def can_speak_as_dm(user, campaign) -> bool:
    """Who may post a logbook personal message as the DM, and move Hit Dice and spell slots by
    hand: the campaign's DM and the administrators."""
    return membership.can_manage(user, campaign)


def can_view(user, character: Character, section: str = "") -> bool:
    """`section` names a part of the character page (`"inventory"`, `"notes"`, ...). Every member
    of the campaign sees everything, except that an *unfinished* character is its editors' only."""
    if character.status == Character.STATUS_DRAFT:
        return can_edit(user, character)
    return membership.is_member(user, character.campaign)


def can_edit(user, character: Character) -> bool:
    """The owner (while still in the campaign), the campaign's DM, or an administrator."""
    if not getattr(user, "is_authenticated", False):
        return False
    if membership.can_manage(user, character.campaign):
        return True
    return character.owner_id == user.id and membership.is_member(user, character.campaign)
