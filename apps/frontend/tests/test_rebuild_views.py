"""The admin's rebuild of a levelled character, through the pages."""

import pytest
from django.contrib.auth import get_user_model

from apps.builder.services import class_choices, creation, origins, rebuild
from apps.builder.services.store import Draft
from apps.builder.tests.conftest import pick_first
from apps.builder.tests.test_progression import autofill, finished, level_up
from apps.characters.models import Character

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


def test_admin_rebuilds_a_level_three_fighter_as_a_wizard(client, alice, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
    character = finished(alice, "fighter")
    level_up(character, "fighter")
    level_up(character, "fighter")
    client.force_login(alice)

    assert "Edit character" in client.get(f"/characters/{character.pk}/").content.decode()
    client.post(f"/characters/{character.pk}/reopen/")
    assert not origins.select_class(character, "wizard")
    for _round in range(3):
        for picker in class_choices.pickers(Draft(character)):
            chosen = pick_first(picker)
            value = chosen[0] if picker.single else chosen
            class_choices.save(character, **{picker.key.removeprefix("class."): value})

    response = client.post(f"/characters/{character.pk}/create/finish/")
    assert response.url == f"/characters/{character.pk}/rebuild/"
    # the wizard is over; its screens lead to the levels
    assert client.get(f"/characters/{character.pk}/create/species/").url == response.url

    page = client.get(response.url)
    html = page.content.decode()
    assert page.status_code == 200 and "Rebuilding: level 2 of 3" in html
    assert "Change class" not in html

    for _ in range(2):
        values = autofill(character, "wizard")
        post = {k: v for k, v in values.items()} | {"action": "commit"}
        done = client.post(response.url, post)
        assert done.status_code == 302
    assert client.get(response.url).url == f"/characters/{character.pk}/"
    character.refresh_from_db()
    assert character.status == Character.STATUS_COMPLETE
    assert not rebuild.has_pending(character)
    assert [(r.klass_id, r.level) for r in character.classes.all()] == [("wizard", 3)]


def test_rebuild_page_needs_a_rebuild_in_progress(client, alice, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
    character = finished(alice, "fighter")
    client.force_login(alice)
    assert client.get(f"/characters/{character.pk}/rebuild/").url == f"/characters/{character.pk}/"
    assert not creation.is_editing(character)
