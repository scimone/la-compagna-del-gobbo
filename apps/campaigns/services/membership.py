"""Who is in which campaign, and what that lets them do. The single place the rest of the app asks
(`characters.services.access` builds on it); nothing else reads memberships directly."""

from django.conf import settings

from apps.campaigns.models import Campaign, CampaignMembership

SESSION_KEY = "campaign_id"


def is_admin(user) -> bool:
    """An administrator (`settings.ADMIN_ACCOUNTS`, matched case-insensitively by username) sees
    and manages every campaign and character."""
    return bool(
        getattr(user, "is_authenticated", False)
        and user.get_username().lower() in settings.ADMIN_ACCOUNTS
    )


def campaigns_for(user):
    """The campaigns `user` can open: their own, or every one for an administrator."""
    if not getattr(user, "is_authenticated", False):
        return Campaign.objects.none()
    if is_admin(user):
        return Campaign.objects.all()
    return Campaign.objects.filter(memberships__user=user).distinct()


def membership_of(user, campaign) -> CampaignMembership | None:
    if campaign is None or not getattr(user, "is_authenticated", False):
        return None
    return CampaignMembership.objects.filter(campaign=campaign, user=user).first()


def role_in(user, campaign) -> str:
    """`"dm"`, `"player"` or `""` (not a member; an administrator reads as `""` too)."""
    membership = membership_of(user, campaign)
    return membership.role if membership else ""


def is_member(user, campaign) -> bool:
    """May `user` open the campaign's content: a member, or an administrator."""
    if campaign is None:
        return False
    return is_admin(user) or membership_of(user, campaign) is not None


def is_dm(user, campaign) -> bool:
    return role_in(user, campaign) == CampaignMembership.DM


def can_manage(user, campaign) -> bool:
    """DM powers: the campaign's DM, or an administrator."""
    return campaign is not None and (is_admin(user) or is_dm(user, campaign))


def shares_campaign(user, other) -> bool:
    return CampaignMembership.objects.filter(
        user=user,
        campaign__in=CampaignMembership.objects.filter(user=other).values("campaign"),
    ).exists()


def resolve_current(user, remembered_id) -> Campaign | None:
    """The campaign the user is looking at: the remembered one if they can still open it, else
    the campaign they joined first (an administrator without one: the first campaign)."""
    available = campaigns_for(user)
    if remembered_id:
        chosen = available.filter(pk=remembered_id).first()
        if chosen:
            return chosen
    if getattr(user, "is_authenticated", False) and not is_admin(user):
        first = (
            CampaignMembership.objects.filter(user=user)
            .select_related("campaign")
            .order_by("joined_at", "pk")
            .first()
        )
        return first.campaign if first else None
    return available.first()


def members(campaign) -> list[CampaignMembership]:
    """The DM first, then the players in the order they joined."""
    rows = list(campaign.memberships.select_related("user"))
    return sorted(rows, key=lambda m: (m.role != CampaignMembership.DM, m.joined_at, m.pk))
