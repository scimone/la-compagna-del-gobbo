"""The level-up page and the buttons that lead to it, driven over HTTP."""

import pytest
from django.contrib.auth import get_user_model

from apps.builder.services import creation, progression
from apps.builder.tests.conftest import build_character

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def bob(db):
    return get_user_model().objects.create_user("bob")


@pytest.fixture
def signed_in(client, alice):
    client.force_login(alice)
    return client


def finished(owner, class_id="fighter", background="soldier", xp=300):
    """A finished level 1 character; 300 XP is what level 2 asks for."""
    character = build_character(owner, class_id, background)
    creation.finalize(character)
    character.experience_points = xp
    character.save()
    character.refresh_from_db()
    return character


def stats_panel(html):
    return html.split('data-panel="stats"')[1].split('data-panel="abilities"')[0]


def test_the_stats_tab_has_a_level_up_button_for_the_owner_only(client, alice, bob):
    character = finished(alice, xp=0)

    client.force_login(alice)
    html = stats_panel(client.get(f"/characters/{character.pk}/").content.decode())
    assert "/levelup/" not in html  # the XP are not full yet
    assert client.get(f"/characters/{character.pk}/levelup/").status_code == 302

    character.experience_points = 300
    character.save()
    html = stats_panel(client.get(f"/characters/{character.pk}/").content.decode())
    assert f'href="/characters/{character.pk}/levelup/"' in html

    client.force_login(bob)
    assert "/levelup/" not in client.get(f"/characters/{character.pk}/").content.decode()
    assert client.get(f"/characters/{character.pk}/levelup/").status_code == 404


def test_the_list_shows_a_level_up_pill_to_the_owner_once_the_xp_allow_it(client, alice, bob):
    character = finished(alice, xp=0)
    client.force_login(alice)
    assert 'class="lvl-pill"' not in client.get("/characters/").content.decode()
    character.experience_points = 300
    character.save()

    assert (
        f'class="lvl-pill" href="/characters/{character.pk}/levelup/"'
        in client.get("/characters/").content.decode()
    )

    client.force_login(bob)
    assert 'class="lvl-pill"' not in client.get("/characters/").content.decode()


def test_signed_out_visitors_are_sent_to_sign_in(client, alice):
    character = finished(alice)

    assert client.get(f"/characters/{character.pk}/levelup/").url.startswith("/account/?next=")


def test_the_page_lists_the_classes_and_explains_why_one_is_not_allowed(signed_in, alice):
    character = finished(alice)

    html = signed_in.get(f"/characters/{character.pk}/levelup/").content.decode()

    assert 'name="klass" value="fighter"' in html
    assert "Needs 13 in the primary ability of" in html  # e.g. Wizard: Int 8
    assert 'name="klass" value="wizard" data-select disabled' in html.replace("\n", " ").replace(
        "  ", " "
    )


def test_choosing_a_class_shows_its_choices_and_saves_nothing(signed_in, alice):
    character = finished(alice)

    html = signed_in.post(
        f"/characters/{character.pk}/levelup/", {"klass": "fighter", "action": "select"}
    ).content.decode()

    assert "Hit points" in html and "lu.hp_mode" in html
    assert "Level up: Fighter 2" in html
    assert progression.total_level(character) == 1


def test_committing_levels_up_and_shows_what_was_gained(signed_in, alice):
    character = finished(alice)
    before = character.max_hit_points

    response = signed_in.post(
        f"/characters/{character.pk}/levelup/",
        {"klass": "fighter", "action": "commit", "lu.hp_mode": "fixed"},
    )

    assert response.url == f"/characters/{character.pk}/levelup/done/"
    done = signed_in.get(response.url).content.decode()
    assert "is now level 2" in done and "Action Surge" in done
    character.refresh_from_db()
    assert progression.total_level(character) == 2 and character.max_hit_points > before
    # the summary is shown once
    assert signed_in.get(response.url).url == f"/characters/{character.pk}/"


def test_an_incomplete_commit_shows_the_problems_and_changes_nothing(signed_in, alice):
    character = finished(alice)

    html = signed_in.post(
        f"/characters/{character.pk}/levelup/",
        {"klass": "fighter", "action": "commit", "lu.hp_mode": "roll"},
    ).content.decode()

    assert "Enter the number you rolled" in html
    assert progression.total_level(character) == 1


def test_a_character_at_level_20_has_no_level_up(signed_in, alice):
    character = finished(alice)
    character.classes.update(level=20)

    assert (
        signed_in.get(f"/characters/{character.pk}/levelup/").url == f"/characters/{character.pk}/"
    )
    html = stats_panel(signed_in.get(f"/characters/{character.pk}/").content.decode())
    assert "/levelup/" not in html


def test_the_subclass_step_keeps_the_class_and_offers_descriptions(signed_in, alice):
    character = finished(alice, "monk", xp=900)
    url = f"/characters/{character.pk}/levelup/"
    progression.commit(character, "monk", {"lu.hp_mode": ["fixed"]})
    character.refresh_from_db()
    character.experience_points = 900
    character.save()

    html = signed_in.post(url, {"klass": "monk", "action": "select"}).content.decode()
    assert 'type="hidden" name="klass" value="monk"' in html
    assert "data-describe" in html

    sub = progression.plan(character, "monk").pickers[0].candidates[0][0]
    # the refresh after picking a subclass must stay on the class, not fall back to the class list
    html = signed_in.post(
        url, {"klass": "monk", "action": "refresh", "lu.subclass": sub}
    ).content.decode()
    assert "Level up: Monk 3" in html
    assert signed_in.get(f"/characters/describe/subclass/{sub}/").status_code == 200


def test_coming_back_to_the_page_restores_the_choices_and_the_review_lists_icons(signed_in, alice):
    character = finished(alice, "monk", xp=900)
    url = f"/characters/{character.pk}/levelup/"
    progression.commit(character, "monk", {"lu.hp_mode": ["fixed"]})
    character.refresh_from_db()
    character.experience_points = 900
    character.save()
    sub = progression.plan(character, "monk").pickers[0].candidates[0][0]

    signed_in.post(url, {"klass": "monk", "action": "refresh", "lu.subclass": sub})
    html = signed_in.get(f"{url}?klass=monk&step=review").content.decode()
    assert f'value="{sub}" checked' in html  # the subclass picked before leaving
    assert 'class="item-thumb' in html  # the features gained, as Handbook rows with an icon
    # the class list again forgets the draft
    signed_in.get(url)
    html = signed_in.get(f"{url}?klass=monk").content.decode()
    assert f'value="{sub}" checked' not in html

    body = signed_in.get(f"/characters/describe/subclass/{sub}/").content.decode()
    assert "level-heading" in body and "feature-link-list" in body


def test_the_review_lists_the_chosen_spells(signed_in, alice):
    character = finished(alice, "wizard", xp=300)
    url = f"/characters/{character.pk}/levelup/"
    plan = progression.plan(character, "wizard")
    picker = next(p for p in plan.pickers if p.key == "lu.spells")
    spell_id, spell_name = picker.candidates[0]
    html = signed_in.post(
        url, {"klass": "wizard", "action": "refresh", "lu.spells": [spell_id]}
    ).content.decode()
    review = html[html.index('data-panel="review"') :]
    assert spell_name in review and f"/world/spells/{spell_id}/" in review


def test_the_review_is_a_change_summary_with_edit_links_and_open_choices(signed_in, alice):
    character = finished(alice, "wizard", xp=300)
    url = f"/characters/{character.pk}/levelup/"
    html = signed_in.post(url, {"klass": "wizard", "action": "refresh"}).content.decode()
    review = html[html.index('data-panel="review"') :]
    assert "rv-block" in review and 'data-goto="0"' in review  # hit points, with its Edit button
    assert "still to make" in review  # the spells are not chosen yet


def test_the_review_lists_what_the_level_raises_by_itself(signed_in, alice):
    character = finished(alice, "wizard", xp=300)
    html = signed_in.post(
        f"/characters/{character.pk}/levelup/", {"klass": "wizard", "action": "refresh"}
    ).content.decode()
    review = html[html.index('data-panel="review"') :]
    assert "rv-effects" in review and "Level 1 spell slots" in review
    assert "Hit Dice" in review and "<b>2d6</b>" in review  # level 1 -> 2
