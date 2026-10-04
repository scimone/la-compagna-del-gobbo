"""The admin panel (activity log by user) and the admin-only "assign character" action."""

from datetime import UTC

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


def test_activity_reads_as_sentences_with_links_to_the_page_concerned(client, users):
    boss, alice = users
    hero = _character(alice)
    Interaction.objects.create(
        username="alice",
        user=alice,
        kind="view",
        route="character-detail",
        path=f"/characters/{hero.pk}/",
        object_id=str(hero.pk),
        method="GET",
        status=200,
    )
    Interaction.objects.create(
        username="alice",
        user=alice,
        kind="action",
        route="character-act",
        action="hp_delta",
        path=f"/characters/{hero.pk}/act/",
        object_id=str(hero.pk),
        method="POST",
        status=200,
    )
    Interaction.objects.create(
        username="alice",
        user=alice,
        kind="view",
        route="character-detail",
        path="/characters/99999/",
        object_id="99999",
        method="GET",
        status=404,
    )
    client.force_login(boss)
    html = client.get("/admin-panel/activity/").content.decode()
    assert "Opened the sheet of Hero" in html and "Played Hero" in html
    assert "Changed hit points" in html
    assert html.count(f'href="/characters/{hero.pk}/"') == 2  # the view, and the change's target
    assert "/act/" not in html.replace("/admin-panel/activity/", "")  # never links to a POST url
    assert "#99999" in html and "no longer exists" in html


def test_activity_is_newest_first(client, users):
    boss, _ = users
    for n in ("first", "second"):
        Interaction.objects.create(
            username="x", kind="view", path=f"/{n}/", method="GET", status=200
        )
    client.force_login(boss)
    html = client.get("/admin-panel/activity/").content.decode()
    assert html.index("/second/") < html.index("/first/")


def test_times_are_shown_in_berlin_and_people_by_name(client, users):
    from datetime import datetime

    boss, alice = users
    alice.first_name = "Alice Rossi"
    alice.save()
    row = Interaction.objects.create(
        username="alice", user=alice, kind="view", path="/x/", method="GET", status=200
    )
    Interaction.objects.filter(pk=row.pk).update(
        created_at=datetime(2026, 1, 15, 22, 30, 5, tzinfo=UTC)
    )
    client.force_login(boss)
    html = client.get("/admin-panel/activity/").content.decode()
    assert "23:30:05" in html  # 22:30 UTC is 23:30 in Berlin (winter)
    assert html.count("Alice Rossi") >= 2  # the row and the filter's option
    assert ">alice" not in html.replace("value=", "")
