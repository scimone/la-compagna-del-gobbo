"""What moves a character between campaigns, and what happens to a member's characters when they
go. Sits above `apps.campaigns` (which knows nothing about characters).

Copying and transferring are for the character's editors (owner or DM) and happen only into a
campaign the person doing it belongs to - so does the owner, for a transfer, or they would lose
sight of their own character.
"""

import copy
import os

from django.core.files.base import ContentFile
from django.db import models, transaction
from django.utils.translation import gettext as _

from apps.campaigns.models import Campaign, CampaignMembership
from apps.campaigns.services import membership
from apps.characters.models import Character
from apps.characters.services import access


def _check_target(user, target: Campaign) -> None:
    if not membership.is_member(user, target):
        raise ValueError(_("You are not a member of that campaign."))


def _clone_file(field_file) -> ContentFile | None:
    if not field_file:
        return None
    try:
        with field_file.open("rb") as handle:
            data = handle.read()
    except (FileNotFoundError, OSError):
        return None
    return ContentFile(data, name=os.path.basename(field_file.name))


def _clone_row(row, **overrides):
    """A copy of `row` (without its primary key), with `overrides` set."""
    clone = copy.copy(row)
    clone.pk = None
    clone.id = None
    clone._state = copy.copy(row._state)
    clone._state.adding = True
    for name, value in overrides.items():
        setattr(clone, name, value)
    return clone


def _child_models():
    """The models whose rows hang off a `Character` (everything but the Logbook, which belongs to
    the campaign, not to the character)."""
    for related in Character._meta.related_objects:
        model = related.related_model
        if model._meta.app_label == "characters" and related.field.name == "character":
            yield model


@transaction.atomic
def copy_character(user, character: Character, target: Campaign) -> Character:
    """An independent duplicate of `character` in `target`, play state included (current HP, spent
    slots, inventory, money, pictures). It belongs to `user`. Logbook entries are not copied."""
    if not access.can_view(user, character):
        raise ValueError(_("You cannot see this character."))
    _check_target(user, target)
    if character.status != Character.STATUS_COMPLETE:
        raise ValueError(_("Only a finished character can be copied."))

    new = _clone_row(character, campaign=target, owner=user, portrait="")
    new.save()
    portrait_file = _clone_file(character.portrait)
    if portrait_file is not None:
        new.portrait.save(portrait_file.name, portrait_file, save=True)

    for model in _child_models():
        files = [f.name for f in model._meta.fields if isinstance(f, models.FileField)]
        # A row may point at another row of the same character (a container's contents): the
        # copies are re-pointed at each other once all of them exist.
        selfs = [
            f.name
            for f in model._meta.fields
            if isinstance(f, models.ForeignKey) and f.remote_field.model is model
        ]
        mapping: dict[int, models.Model] = {}
        for row in model.objects.filter(character=character).order_by("pk"):
            overrides = {"character": new}
            for name in files:
                overrides[name] = _clone_file(getattr(row, name)) or ""
            for name in selfs:
                overrides[name] = None
            clone = _clone_row(row, **overrides)
            clone.save()
            mapping[row.pk] = clone
        for row in model.objects.filter(character=character, pk__in=mapping):
            for name in selfs:
                old = getattr(row, f"{name}_id")
                if old in mapping:
                    clone = mapping[row.pk]
                    setattr(clone, f"{name}_id", mapping[old].pk)
                    clone.save(update_fields=[name])
    return new


def transfer_character(user, character: Character, target: Campaign) -> Character:
    """Move `character` to `target`; its owner has to be a member there too. The Logbook entries
    that mention it stay in the old campaign."""
    if not access.can_edit(user, character):
        raise ValueError(_("You cannot move this character."))
    _check_target(user, target)
    if target.pk == character.campaign_id:
        raise ValueError(_("The character is already in that campaign."))
    if character.owner_id and not membership.is_member(character.owner, target):
        raise ValueError(_("The character's owner is not a member of that campaign."))
    character.campaign = target
    character.save(update_fields=["campaign"])
    return character


def characters_lost_on_leaving(campaign: Campaign, user) -> list[Character]:
    """The characters of `user` that leaving (or being removed from) `campaign` deletes."""
    return list(Character.objects.filter(campaign=campaign, owner=user).order_by("name", "pk"))


@transaction.atomic
def remove_member(campaign: Campaign, user) -> int:
    """Take `user` out of `campaign`, deleting their characters in it. Returns how many characters
    went. The DM cannot leave: they hand the role over first."""
    row = (
        CampaignMembership.objects.select_for_update().filter(campaign=campaign, user=user).first()
    )
    if row is None:
        raise ValueError(_("This person is not in the campaign."))
    if row.role == CampaignMembership.DM:
        raise ValueError(_("The DM has to hand the DM role to someone else first."))
    lost = characters_lost_on_leaving(campaign, user)
    for character in lost:
        character.delete()
    row.delete()
    return len(lost)


def delete_campaign(campaign: Campaign) -> None:
    """Delete an empty campaign (no characters): its Logbook, members and invites go with it."""
    if campaign.characters.exists():
        raise ValueError(_("Delete or move the campaign's characters first."))
    campaign.delete()
