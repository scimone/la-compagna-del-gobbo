"""The admin panel (activity log by user) and the admin-only "assign character" action."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.characters.models import Character
from apps.frontend.models import Interaction


@pytest.fixture
def users(db):
    User = get_user_model()
    return User.objects.create_user("boss"), User.objects.create_user("alice")


@pytest.fixture(autouse=True)
def admins():
    with override_settings(ADMIN_ACCOUNTS=["boss"]):
        yield


def test_the_panel_is_hidden_from_everyone_but_admins(client, users):
    boss, alice = users
    assert client.get("/admin-panel/activity/").status_code == 404
    client.force_login(alice)
    assert client.get("/admin-panel/").status_code == 404
    assert client.get("/admin-panel/activity/").status_code == 404
    assert "/admin-panel/" not in client.get("/account/").content.decode()
    client.force_login(boss)
    assert client.get("/admin-panel/").status_code == 200
    assert "/admin-panel/" in client.get("/account/").content.decode()


def test_activity_can_be_filtered_by_user(client, users):
    boss, alice = users
    Interaction.objects.create(
        username="alice", user=alice, kind="view", path="/alice-page/", method="GET", status=200
    )
    Interaction.objects.create(
        username="", kind="view", path="/anon-page/", method="GET", status=200
    )
    client.force_login(boss)

    everyone = client.get("/admin-panel/activity/").content.decode()
    assert "/alice-page/" in everyone and "/anon-page/" in everyone

    only_alice = client.get("/admin-panel/activity/?user=alice").content.decode()
    assert "/alice-page/" in only_alice and "/anon-page/" not in only_alice

    anon = client.get("/admin-panel/activity/?user=__anonymous__").content.decode()
    assert "/anon-page/" in anon and "/alice-page/" not in anon


def _character(owner):
    return Character.objects.create(name="Hero", owner=owner, status=Character.STATUS_COMPLETE)


def test_only_an_admin_can_assign_a_character(client, users):
    boss, alice = users
    hero = _character(boss)
    client.force_login(alice)
    assert client.get(f"/characters/{hero.pk}/assign/").status_code == 404
    assert client.post(f"/characters/{hero.pk}/assign/", {"owner": alice.pk}).status_code == 404
    hero.refresh_from_db()
    assert hero.owner == boss

    client.force_login(boss)
    assert client.get(f"/characters/{hero.pk}/assign/").status_code == 200
    response = client.post(f"/characters/{hero.pk}/assign/", {"owner": alice.pk})
    assert response.status_code == 302
    hero.refresh_from_db()
    assert hero.owner == alice
