"""Creating and running a campaign: the DM role, the join link, deleting. Anything that deletes
characters (a member leaving or being removed) lives in `characters.services.campaign_ops`, which
sits above this app."""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.campaigns.models import Campaign, CampaignMembership
from apps.campaigns.models.campaign import new_join_code

NAME_MAX = 100


def create_campaign(user, name: str, description: str = "") -> Campaign:
    """A new campaign whose DM is `user`."""
    name = (name or "").strip()[:NAME_MAX]
    if not name:
        raise ValueError(_("A campaign needs a name."))
    with transaction.atomic():
        campaign = Campaign.objects.create(
            name=name, description=(description or "").strip()[:2000], created_by=user
        )
        CampaignMembership.objects.create(campaign=campaign, user=user, role=CampaignMembership.DM)
    return campaign


def update_campaign(campaign: Campaign, name: str, description: str = "") -> None:
    name = (name or "").strip()[:NAME_MAX]
    if not name:
        raise ValueError(_("A campaign needs a name."))
    campaign.name = name
    campaign.description = (description or "").strip()[:2000]
    campaign.save(update_fields=["name", "description"])


@transaction.atomic
def transfer_dm(campaign: Campaign, new_dm) -> None:
    """Hand the DM role to `new_dm`, a member; the previous DM becomes a player."""
    target = (
        CampaignMembership.objects.select_for_update()
        .filter(campaign=campaign, user=new_dm)
        .first()
    )
    if target is None:
        raise ValueError(_("The new DM has to be a member of the campaign."))
    if target.role == CampaignMembership.DM:
        return
    CampaignMembership.objects.filter(campaign=campaign, role=CampaignMembership.DM).update(
        role=CampaignMembership.PLAYER
    )
    target.role = CampaignMembership.DM
    target.save(update_fields=["role"])


def join_via_code(user, code: str) -> Campaign:
    """Join the campaign whose join link carries `code` (as a player); a member just gets the
    campaign back."""
    campaign = Campaign.objects.filter(join_code=code, join_enabled=True).first() if code else None
    if campaign is None:
        raise ValueError(_("This join link is not valid any more."))
    CampaignMembership.objects.get_or_create(
        campaign=campaign, user=user, defaults={"role": CampaignMembership.PLAYER}
    )
    return campaign


def regenerate_join_code(campaign: Campaign) -> None:
    campaign.join_code = new_join_code()
    campaign.save(update_fields=["join_code"])


def set_join_enabled(campaign: Campaign, enabled: bool) -> None:
    campaign.join_enabled = enabled
    campaign.save(update_fields=["join_enabled"])
