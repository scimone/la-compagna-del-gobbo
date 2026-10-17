from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.campaigns.models import CampaignInvite, CampaignMembership
from apps.campaigns.services import invites, lifecycle, membership

pytestmark = pytest.mark.no_default_campaign


@pytest.fixture
def dm(make_user):
    return make_user("dm")


@pytest.fixture
def campaign(dm):
    return lifecycle.create_campaign(dm, "  Obelisco  ", "desc")


def test_creating_a_campaign_makes_the_creator_its_dm(campaign, dm):
    assert campaign.name == "Obelisco"
    assert membership.role_in(dm, campaign) == "dm"
    assert membership.can_manage(dm, campaign)


def test_a_campaign_needs_a_name(dm):
    with pytest.raises(ValueError):
        lifecycle.create_campaign(dm, "   ")


def test_the_database_allows_one_dm_per_campaign(campaign, make_user):
    other = make_user("other")
    with pytest.raises(IntegrityError), transaction.atomic():
        CampaignMembership.objects.create(campaign=campaign, user=other, role="dm")


def test_transferring_the_dm_role_swaps_it(campaign, dm, make_user):
    anna = make_user("anna")
    CampaignMembership.objects.create(campaign=campaign, user=anna)

    lifecycle.transfer_dm(campaign, anna)

    assert membership.role_in(anna, campaign) == "dm"
    assert membership.role_in(dm, campaign) == "player"
    assert campaign.memberships.filter(role="dm").count() == 1


def test_the_dm_role_goes_to_a_member_only(campaign, make_user):
    with pytest.raises(ValueError):
        lifecycle.transfer_dm(campaign, make_user("stranger"))


def test_nobody_outside_a_campaign_is_a_member(campaign, make_user, settings):
    stranger = make_user("stranger")
    assert not membership.is_member(stranger, campaign)
    assert list(membership.campaigns_for(stranger)) == []
    settings.ADMIN_ACCOUNTS = ["stranger"]
    assert membership.is_member(stranger, campaign)  # admins see every campaign
    assert list(membership.campaigns_for(stranger)) == [campaign]
    assert membership.can_manage(stranger, campaign)


def test_the_current_campaign_falls_back_to_the_first_joined(campaign, dm, make_user):
    second = lifecycle.create_campaign(dm, "Second")
    assert membership.resolve_current(dm, second.pk) == second
    assert membership.resolve_current(dm, 999999) == campaign
    assert membership.resolve_current(make_user("new"), None) is None


# --- invitations -------------------------------------------------------------------------------


def test_an_invite_is_stored_lower_case_and_not_repeated(campaign, dm):
    first = invites.invite(campaign, dm, " Ann@Gmail.com ")
    again = invites.invite(campaign, dm, "ann@gmail.COM")

    assert first.email == "ann@gmail.com" and again.pk == first.pk
    assert CampaignInvite.objects.count() == 1


def test_an_invite_needs_a_valid_address_and_a_non_member(campaign, dm):
    with pytest.raises(ValueError):
        invites.invite(campaign, dm, "not an address")
    with pytest.raises(ValueError):
        invites.invite(campaign, dm, "dm@example.com")  # already in


def test_invites_are_rate_limited(campaign, dm):
    for n in range(invites.RATE_LIMIT):
        invites.invite(campaign, dm, f"p{n}@example.com")
    with pytest.raises(ValueError):
        invites.invite(campaign, dm, "one-too-many@example.com")


def test_the_invited_person_sees_and_accepts_it(campaign, dm, make_user):
    ann = make_user("ann", "Ann@Gmail.com")
    invite = invites.invite(campaign, dm, "ann@gmail.com")

    assert list(invites.pending_for(ann)) == [invite]
    invites.accept(invite, ann)

    assert membership.role_in(ann, campaign) == "player"
    assert list(invites.pending_for(ann)) == []
    with pytest.raises(ValueError):
        invites.accept(invite, ann)  # used up


def test_an_invite_is_for_its_address_only(campaign, dm, make_user):
    invite = invites.invite(campaign, dm, "ann@gmail.com")
    eve = make_user("eve", "eve@gmail.com")

    assert list(invites.pending_for(eve)) == []
    with pytest.raises(ValueError):
        invites.accept(invite, eve)
    assert not membership.is_member(eve, campaign)


def test_an_invite_expires_after_about_six_months(campaign, dm, make_user):
    ann = make_user("ann", "ann@gmail.com")
    invite = invites.invite(campaign, dm, "ann@gmail.com")
    assert timedelta(days=180) < invite.expires_at - timezone.now() < timedelta(days=190)

    invite.expires_at = timezone.now() - timedelta(seconds=1)
    invite.save()

    assert list(invites.pending_for(ann)) == []
    with pytest.raises(ValueError):
        invites.accept(invite, ann)
    renewed = invites.invite(campaign, dm, "ann@gmail.com")  # inviting again renews it
    assert renewed.pk == invite.pk and renewed.is_open


def test_declining_and_withdrawing(campaign, dm, make_user):
    ann = make_user("ann", "ann@gmail.com")
    declined = invites.invite(campaign, dm, "ann@gmail.com")
    invites.decline(declined, ann)
    assert list(invites.pending_for(ann)) == []

    withdrawn = invites.invite(campaign, dm, "ann@gmail.com")
    invites.revoke(withdrawn)
    assert list(invites.open_invites(campaign)) == []


# --- join link ---------------------------------------------------------------------------------


def test_join_link_adds_a_player_until_switched_off_or_replaced(campaign, make_user):
    ann, bob = make_user("ann"), make_user("bob")
    code = campaign.join_code

    assert lifecycle.join_via_code(ann, code) == campaign
    assert membership.role_in(ann, campaign) == "player"
    assert lifecycle.join_via_code(ann, code) == campaign  # joining twice changes nothing

    lifecycle.set_join_enabled(campaign, False)
    with pytest.raises(ValueError):
        lifecycle.join_via_code(bob, code)
    lifecycle.set_join_enabled(campaign, True)
    lifecycle.regenerate_join_code(campaign)
    with pytest.raises(ValueError):
        lifecycle.join_via_code(bob, code)
    lifecycle.join_via_code(bob, campaign.join_code)
    assert campaign.memberships.count() == 3
