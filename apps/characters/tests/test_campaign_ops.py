import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile

from apps.campaigns.models import CampaignMembership
from apps.campaigns.services import lifecycle
from apps.characters.models import Character, CharacterCurrency, CharacterInventoryItem
from apps.characters.services import access, campaign_ops

pytestmark = pytest.mark.no_default_campaign


@pytest.fixture
def people(db):
    User = get_user_model()
    return {
        n: User.objects.create_user(username=n, email=f"{n}@example.com")
        for n in "dm ann bob".split()
    }


@pytest.fixture
def world(people):
    obelisk = lifecycle.create_campaign(people["dm"], "Obelisco")
    other = lifecycle.create_campaign(people["ann"], "Other")
    for user in (people["ann"], people["bob"]):
        CampaignMembership.objects.get_or_create(campaign=obelisk, user=user)
    return obelisk, other


@pytest.fixture
def hero(world, people, species, background, equipment_item, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    obelisk, _other = world
    hero = Character.objects.create(
        campaign=obelisk,
        owner=people["ann"],
        name="Gobbo",
        species=species,
        background=background,
        max_hit_points=30,
        current_hit_points=11,
        experience_points=900,
    )
    CharacterCurrency.objects.create(character=hero, gold=42)
    bag = CharacterInventoryItem.objects.create(character=hero, equipment=equipment_item)
    CharacterInventoryItem.objects.create(
        character=hero, equipment=equipment_item, parent=bag, quantity=3
    )
    hero.portrait.save("p.webp", ContentFile(b"image-bytes"))
    return hero


def test_a_copy_keeps_the_play_state_and_is_independent(hero, world, people):
    obelisk, other = world
    campaign_ops.copy_character(people["ann"], hero, other)
    copy = Character.objects.get(campaign=other)

    assert (copy.name, copy.current_hit_points, copy.experience_points) == ("Gobbo", 11, 900)
    assert copy.owner == people["ann"] and copy.pk != hero.pk
    assert copy.currency.gold == 42
    items = {i.quantity: i for i in copy.inventory_items.all()}
    assert items[3].parent == items[1] and items[1].parent is None  # the bag's contents
    assert copy.portrait.read() == b"image-bytes" and copy.portrait.name != hero.portrait.name

    copy.current_hit_points = 1
    copy.save()
    hero.refresh_from_db()
    assert hero.current_hit_points == 11
    assert hero.inventory_items.count() == 2 and hero.campaign == obelisk


def test_anyone_who_sees_a_character_may_copy_it_into_their_own_campaign(hero, world, people):
    obelisk, other = world
    copy = campaign_ops.copy_character(people["bob"], hero, obelisk)  # even into the same one
    assert copy.owner == people["bob"] and copy.campaign == obelisk

    with pytest.raises(ValueError):  # bob is not in "Other"
        campaign_ops.copy_character(people["bob"], hero, other)
    eve = get_user_model().objects.create_user(username="eve")
    CampaignMembership.objects.create(campaign=other, user=eve)
    with pytest.raises(ValueError):  # eve cannot see the original
        campaign_ops.copy_character(eve, hero, other)


def test_a_transfer_moves_the_character_for_its_owner_or_dm(hero, world, people):
    obelisk, other = world
    campaign_ops.transfer_character(people["ann"], hero, other)
    assert Character.objects.get(pk=hero.pk).campaign == other
    assert access.can_edit(people["ann"], hero)
    assert not access.can_view(people["bob"], hero)  # bob is not in "Other"


def test_a_transfer_needs_an_editor_and_a_target_the_owner_belongs_to(hero, world, people):
    obelisk, other = world
    with pytest.raises(ValueError):
        campaign_ops.transfer_character(people["bob"], hero, obelisk)  # not his
    third = lifecycle.create_campaign(people["dm"], "DM only")
    with pytest.raises(ValueError):  # the DM may move it, but ann has to be there too
        campaign_ops.transfer_character(people["dm"], hero, third)
    with pytest.raises(ValueError):
        campaign_ops.transfer_character(people["ann"], hero, obelisk)  # already there


def test_logbook_entries_stay_when_a_character_moves(hero, world, people):
    from apps.frontend.models import LogEntry

    obelisk, other = world
    entry = LogEntry.objects.create(
        campaign=obelisk, author=people["ann"], character=hero, date="2026-01-01", text="x"
    )
    campaign_ops.transfer_character(people["ann"], hero, other)
    entry.refresh_from_db()
    assert entry.campaign == obelisk


def test_leaving_deletes_your_characters_and_the_dm_cannot_leave(hero, world, people):
    obelisk, other = world
    kept = Character.objects.create(campaign=other, owner=people["ann"], name="Elsewhere")

    assert [c.name for c in campaign_ops.characters_lost_on_leaving(obelisk, people["ann"])] == [
        "Gobbo"
    ]
    assert campaign_ops.remove_member(obelisk, people["ann"]) == 1

    assert not Character.objects.filter(pk=hero.pk).exists()
    assert Character.objects.filter(pk=kept.pk).exists()
    assert not obelisk.memberships.filter(user=people["ann"]).exists()
    with pytest.raises(ValueError):
        campaign_ops.remove_member(obelisk, people["dm"])
    lifecycle.transfer_dm(obelisk, people["bob"])
    campaign_ops.remove_member(obelisk, people["dm"])  # fine once someone else is DM


def test_a_campaign_with_characters_cannot_be_deleted(hero, world):
    obelisk, other = world
    with pytest.raises(ValueError):
        campaign_ops.delete_campaign(obelisk)
    campaign_ops.delete_campaign(other)
    assert not type(other).objects.filter(pk=other.pk).exists()


def test_access_follows_the_campaign(hero, world, people, settings):
    obelisk, other = world
    stranger = get_user_model().objects.create_user(username="eve")

    assert access.can_view(people["bob"], hero) and not access.can_edit(people["bob"], hero)
    assert access.can_edit(people["ann"], hero) and access.can_edit(people["dm"], hero)
    assert not access.can_view(stranger, hero) and not access.can_edit(stranger, hero)
    settings.ADMIN_ACCOUNTS = ["eve"]
    assert access.can_view(stranger, hero) and access.can_edit(stranger, hero)

    CampaignMembership.objects.filter(campaign=obelisk, user=people["ann"]).delete()
    assert not access.can_edit(people["ann"], hero)  # an owner who left no longer edits
