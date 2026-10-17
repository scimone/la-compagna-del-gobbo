"""E-mail invitations. An invite is addressed to an e-mail and matched against the verified
e-mail of the account that signs in, so there is nothing to send and nothing to guess."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.campaigns.models import Campaign, CampaignInvite, CampaignMembership
from apps.campaigns.models.invite import default_expiry

#: Invites one account may create per hour.
RATE_LIMIT = 20


def normalise(email: str) -> str:
    return (email or "").strip().lower()


def invite(campaign: Campaign, invited_by, email: str) -> CampaignInvite:
    email = normalise(email)
    try:
        validate_email(email)
    except ValidationError:
        raise ValueError(_("That is not a valid e-mail address.")) from None
    if CampaignMembership.objects.filter(campaign=campaign, user__email__iexact=email).exists():
        raise ValueError(_("This person is already in the campaign."))
    recent = CampaignInvite.objects.filter(
        invited_by=invited_by, created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recent >= RATE_LIMIT:
        raise ValueError(_("Too many invitations in a short time. Try again later."))
    with transaction.atomic():
        open_invite = CampaignInvite.objects.filter(
            campaign=campaign, email=email, accepted_at=None, revoked_at=None
        ).first()
        if open_invite:  # already invited: just renew it
            open_invite.expires_at = default_expiry()
            open_invite.save(update_fields=["expires_at"])
            return open_invite
        return CampaignInvite.objects.create(campaign=campaign, email=email, invited_by=invited_by)


def open_invites(campaign: Campaign):
    return campaign.invites.filter(
        accepted_at=None, revoked_at=None, expires_at__gt=timezone.now()
    ).select_related("invited_by")


def pending_for(user):
    """The open invitations addressed to `user`'s e-mail."""
    email = normalise(getattr(user, "email", ""))
    if not getattr(user, "is_authenticated", False) or not email:
        return CampaignInvite.objects.none()
    return CampaignInvite.objects.filter(
        email=email, accepted_at=None, revoked_at=None, expires_at__gt=timezone.now()
    ).select_related("campaign", "invited_by")


def _addressed_to(invite_: CampaignInvite, user) -> bool:
    return invite_.is_open and normalise(user.email) == invite_.email


def accept(invite_: CampaignInvite, user) -> CampaignMembership:
    if not _addressed_to(invite_, user):
        raise ValueError(_("This invitation is not valid any more."))
    with transaction.atomic():
        membership, _created = CampaignMembership.objects.get_or_create(
            campaign=invite_.campaign,
            user=user,
            defaults={"role": CampaignMembership.PLAYER},
        )
        invite_.accepted_at = timezone.now()
        invite_.save(update_fields=["accepted_at"])
    return membership


def decline(invite_: CampaignInvite, user) -> None:
    if not _addressed_to(invite_, user):
        raise ValueError(_("This invitation is not valid any more."))
    revoke(invite_)


def revoke(invite_: CampaignInvite) -> None:
    if invite_.accepted_at is None and invite_.revoked_at is None:
        invite_.revoked_at = timezone.now()
        invite_.save(update_fields=["revoked_at"])
