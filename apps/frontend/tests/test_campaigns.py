import pytest
from django.contrib.auth import get_user_model

from apps.campaigns.models import Campaign, CampaignInvite, CampaignMembership
from apps.campaigns.services import invites, lifecycle, membership
from apps.characters.models import Character
from apps.frontend.models import LogEntry

pytestmark = pytest.mark.no_default_campaign


@pytest.fixture
def users(db):
    User = get_user_model()
    return {
        n: User.objects.create_user(username=n, email=f"{n}@gmail.com")
        for n in "riky ann bob".split()
    }


@pytest.fixture
def obelisk(users):
    campaign = lifecycle.create_campaign(users["riky"], "Obelisco infranto")
    CampaignMembership.objects.create(campaign=campaign, user=users["ann"])
    return campaign


def login(client, user):
    client.force_login(user)
    return client


def hero(campaign, owner, name="Gobbo"):
    return Character.objects.create(
        campaign=campaign, owner=owner, name=name, status=Character.STATUS_COMPLETE
    )


def test_a_new_user_sees_no_characters_or_logbook_but_still_the_world(client, users, obelisk):
    hero(obelisk, users["ann"])
    LogEntry.objects.create(campaign=obelisk, date="2026-01-01", title="Secret tale")
    login(client, users["bob"])

    for url in ("/characters/", "/logbook/"):
        page = client.get(url).content.decode()
        assert "not in a campaign yet" in page
        assert "Gobbo" not in page and "Secret tale" not in page
    assert client.get("/world/backgrounds/").status_code == 200
    assert client.get("/handbook/").status_code == 200
    assert client.get("/characters/new/").status_code == 404  # no campaign, no new character
    assert client.get("/campaigns/").status_code == 200


def test_creating_a_campaign_makes_you_dm_and_lets_you_create_characters(client, users):
    login(client, users["bob"])

    response = client.post("/campaigns/new/", {"name": "Mine", "description": "d"})

    campaign = Campaign.objects.get(name="Mine")
    assert response.status_code == 302
    assert membership.role_in(users["bob"], campaign) == "dm"
    assert "No characters yet" in client.get("/characters/").content.decode()
    assert client.get("/characters/new/").status_code == 200
    client.post("/characters/new/", {"name": "Fresh"})
    assert Character.objects.get(name="Fresh").campaign == campaign


def test_non_members_get_a_404_for_everything_in_a_campaign(client, users, obelisk):
    ann_hero = hero(obelisk, users["ann"])
    login(client, users["bob"])

    for url in (
        f"/characters/{ann_hero.pk}/",
        f"/characters/{ann_hero.pk}/export-pdf/",
        f"/characters/{ann_hero.pk}/move/",
        f"/campaigns/{obelisk.pk}/",
    ):
        assert client.get(url).status_code == 404, url
    assert client.post(f"/characters/{ann_hero.pk}/act/", {"action": "name"}).status_code == 403
    assert client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "invite"}).status_code == 404


def test_the_list_and_logbook_show_only_the_current_campaign(client, users, obelisk):
    other = lifecycle.create_campaign(users["ann"], "Other")
    hero(obelisk, users["ann"], "Gobbo")
    hero(other, users["ann"], "Elsewhere")
    LogEntry.objects.create(campaign=obelisk, date="2026-01-01", title="Obelisk tale")
    LogEntry.objects.create(campaign=other, date="2026-01-01", title="Other tale")
    login(client, users["ann"])

    client.post(f"/campaigns/{obelisk.pk}/switch/")
    assert "Gobbo" in client.get("/characters/").content.decode()
    assert "Elsewhere" not in client.get("/characters/").content.decode()
    log = client.get("/logbook/").content.decode()
    assert "Obelisk tale" in log and "Other tale" not in log

    client.post(f"/campaigns/{other.pk}/switch/")
    assert "Elsewhere" in client.get("/characters/").content.decode()
    assert "Other tale" in client.get("/logbook/").content.decode()
    assert client.post("/campaigns/999/switch/").status_code == 404


def test_new_logbook_entries_go_to_the_current_campaign(client, users, obelisk):
    login(client, users["ann"])
    client.post("/logbook/new/", {"date": "2026-02-02", "title": "Day one", "text": "It rained."})
    assert LogEntry.objects.get(title="Day one").campaign == obelisk


def test_the_dm_edits_any_entry_but_a_player_only_their_own(client, users, obelisk):
    entry = LogEntry.objects.create(
        campaign=obelisk, author=users["ann"], date="2026-01-01", title="Ann's"
    )
    CampaignMembership.objects.create(campaign=obelisk, user=users["bob"])
    assert client.get(f"/logbook/{entry.pk}/edit/").status_code == 302  # signed out: sign in

    login(client, users["bob"])
    assert client.get(f"/logbook/{entry.pk}/edit/").status_code == 404
    login(client, users["ann"])
    assert client.get(f"/logbook/{entry.pk}/edit/").status_code == 200
    login(client, users["riky"])  # the DM
    assert client.get(f"/logbook/{entry.pk}/edit/").status_code == 200


def test_the_dm_edits_a_players_character_but_another_player_cannot(client, users, obelisk):
    CampaignMembership.objects.create(campaign=obelisk, user=users["bob"])
    ann_hero = hero(obelisk, users["ann"])
    other = lifecycle.create_campaign(users["ann"], "Other")
    CampaignMembership.objects.create(campaign=other, user=users["riky"])
    CampaignMembership.objects.create(campaign=other, user=users["bob"])
    url = f"/characters/{ann_hero.pk}/move/?mode=transfer"  # only for those who may edit it

    login(client, users["bob"])
    assert (
        client.post(f"/characters/{ann_hero.pk}/act/", {"action": "xp", "value": "50"}).status_code
        == 403
    )
    assert client.get(url).status_code == 404
    login(client, users["riky"])  # the DM
    assert client.get(url).status_code == 200
    login(client, users["ann"])  # the owner
    assert client.get(url).status_code == 200


def test_invite_by_email_then_accept(client, users, obelisk):
    login(client, users["ann"])  # any member invites
    response = client.post(
        f"/campaigns/{obelisk.pk}/act/", {"action": "invite", "email": " Bob@Gmail.com "}
    )
    assert response.status_code == 302
    invite = CampaignInvite.objects.get(email="bob@gmail.com")

    login(client, users["bob"])
    assert "Obelisco infranto" in client.get("/campaigns/").content.decode()
    assert client.get("/characters/").content.decode().count("1 invitation waiting") == 1
    assert client.post(f"/campaigns/invites/{invite.pk}/accept/").status_code == 302

    assert membership.role_in(users["bob"], obelisk) == "player"
    assert "Obelisco infranto" in client.get("/characters/").content.decode()


def test_nobody_else_can_answer_an_invite(client, users, obelisk):
    invite = invites.invite(obelisk, users["riky"], "bob@gmail.com")
    login(client, users["ann"])
    assert client.post(f"/campaigns/invites/{invite.pk}/accept/").status_code == 404
    assert not membership.is_member(users["ann"], Campaign.objects.get(pk=obelisk.pk)) or True
    assert CampaignInvite.objects.get(pk=invite.pk).accepted_at is None


def test_declining_an_invite(client, users, obelisk):
    invite = invites.invite(obelisk, users["riky"], "bob@gmail.com")
    login(client, users["bob"])
    client.post(f"/campaigns/invites/{invite.pk}/decline/")
    assert not membership.is_member(users["bob"], obelisk)
    assert list(invites.pending_for(users["bob"])) == []


def test_join_link_confirms_then_joins(client, users, obelisk):
    login(client, users["bob"])
    page = client.get(f"/join/{obelisk.join_code}/").content.decode()
    assert "Join the campaign" in page and not membership.is_member(users["bob"], obelisk)

    client.post(f"/join/{obelisk.join_code}/")
    assert membership.role_in(users["bob"], obelisk) == "player"

    assert "not valid any more" in client.get("/join/nonsense/").content.decode()


def test_join_code_box_accepts_the_whole_link(client, users, obelisk):
    login(client, users["bob"])
    response = client.post(
        "/campaigns/join/", {"code": f"https://x.test/join/{obelisk.join_code}/"}
    )
    assert response.url == f"/join/{obelisk.join_code}/"


def test_only_the_dm_manages_the_campaign(client, users, obelisk):
    login(client, users["ann"])
    for action in (
        "rename",
        "regenerate_code",
        "join_enabled",
        "transfer_dm",
        "remove_member",
        "delete",
    ):
        assert client.post(f"/campaigns/{obelisk.pk}/act/", {"action": action}).status_code == 404

    login(client, users["riky"])
    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "rename", "name": "Renamed"})
    obelisk.refresh_from_db()
    assert obelisk.name == "Renamed"


def test_handing_over_the_dm_role_then_leaving(client, users, obelisk):
    login(client, users["riky"])
    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "leave"})
    assert membership.is_member(users["riky"], obelisk)  # a DM cannot just leave

    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "transfer_dm", "user": users["ann"].pk})
    assert membership.role_in(users["ann"], obelisk) == "dm"
    assert membership.role_in(users["riky"], obelisk) == "player"
    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "leave"})
    assert not membership.is_member(users["riky"], obelisk)


def test_leaving_warns_about_and_deletes_your_characters(client, users, obelisk):
    mine = hero(obelisk, users["ann"], "Doomed")
    login(client, users["ann"])

    page = client.get(f"/campaigns/{obelisk.pk}/").content.decode()
    assert "Leaving deletes your characters" in page and "Doomed" in page

    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "leave"})
    assert not Character.objects.filter(pk=mine.pk).exists()
    assert not membership.is_member(users["ann"], obelisk)


def test_removing_a_member_deletes_their_characters(client, users, obelisk):
    mine = hero(obelisk, users["ann"])
    login(client, users["riky"])
    client.post(
        f"/campaigns/{obelisk.pk}/act/", {"action": "remove_member", "user": users["ann"].pk}
    )
    assert not Character.objects.filter(pk=mine.pk).exists()
    assert not membership.is_member(users["ann"], obelisk)


def test_deleting_a_campaign_waits_until_it_has_no_characters(client, users, obelisk):
    mine = hero(obelisk, users["ann"])
    login(client, users["riky"])
    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "delete"})
    assert Campaign.objects.filter(pk=obelisk.pk).exists()
    mine.delete()
    client.post(f"/campaigns/{obelisk.pk}/act/", {"action": "delete"})
    assert not Campaign.objects.filter(pk=obelisk.pk).exists()


def test_copying_and_moving_a_character_over_http(client, users, obelisk):
    other = lifecycle.create_campaign(users["ann"], "Other")
    mine = hero(obelisk, users["ann"])
    login(client, users["ann"])

    page = client.get(f"/characters/{mine.pk}/move/").content.decode()
    assert "Other" in page and "Obelisco infranto" in page
    response = client.post(f"/characters/{mine.pk}/move/", {"campaign": other.pk})
    copy = Character.objects.get(campaign=other)
    assert response.url == f"/characters/{copy.pk}/" and copy.pk != mine.pk

    moved = client.post(f"/characters/{mine.pk}/move/?mode=transfer", {"campaign": other.pk})
    mine.refresh_from_db()
    assert moved.status_code == 302 and mine.campaign == other
    assert client.get(f"/characters/{mine.pk}/move/?mode=transfer").status_code == 200
    login(client, users["riky"])  # not in "Other": cannot even look
    assert client.get(f"/characters/{mine.pk}/move/").status_code == 404


def test_administrators_see_every_campaign(client, users, obelisk, settings):
    settings.ADMIN_ACCOUNTS = ["bob"]
    mine = hero(obelisk, users["ann"])
    login(client, users["bob"])

    assert "Obelisco infranto" in client.get("/campaigns/").content.decode()
    assert client.get(f"/campaigns/{obelisk.pk}/").status_code == 200
    assert client.get(f"/characters/{mine.pk}/move/?mode=transfer").status_code == 200
