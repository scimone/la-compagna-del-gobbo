"""The Characters menu and creation wizard, driven over HTTP like a browser would."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.builder.services import creation
from apps.builder.tests.conftest import build_character
from apps.characters.models import Character

pytestmark = pytest.mark.usefixtures("imported_rules")

STEP_URL = "/characters/{pk}/create/{step}/"


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


def step(pk, name):
    return STEP_URL.format(pk=pk, step=name)


# --- the list, the + button, access ---------------------------------------


def test_list_is_public_and_shows_the_plus_button(client, db):
    response = client.get("/characters/")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="/characters/new/"' in html and "No characters yet" in html


def test_signed_out_plus_goes_to_sign_in_and_back(client, db):
    response = client.get("/characters/new/")

    assert response.status_code == 302
    assert response.url.startswith("/account/?next=/characters/new/")


def test_starting_a_character_creates_an_owned_draft_at_the_class_step(signed_in, alice):
    response = signed_in.post("/characters/new/", {"name": "Mira"})

    character = Character.objects.get(name="Mira")
    assert character.owner == alice and character.status == Character.STATUS_DRAFT
    assert response.url == step(character.pk, "class")
    assert signed_in.get(response.url).status_code == 200
    # The unfinished character is listed for its owner, as "in creation".
    assert "In creation" in signed_in.get("/characters/").content.decode()


def test_everyone_sees_every_finished_character_but_only_the_owner_edits(client, alice, bob, db):
    mira = build_character(alice, "wizard", name="Mira")
    creation.finalize(mira)

    # Anonymous and another account both see it, with its owner named.
    for viewer in (client,):
        html = viewer.get("/characters/").content.decode()
        assert "Mira" in html and "alice" in html
        assert viewer.get(f"/characters/{mira.pk}/").status_code == 200
    client.force_login(bob)
    assert "Mira" in client.get("/characters/").content.decode()
    assert client.get(f"/characters/{mira.pk}/").status_code == 200
    # A finished character has no wizard: it redirects to its page.
    assert client.get(step(mira.pk, "class")).status_code == 302


def test_someone_elses_unfinished_character_is_private(client, alice, bob):
    draft = creation.start_draft(alice, "Secret draft")

    client.force_login(bob)
    assert "Secret draft" not in client.get("/characters/").content.decode()
    assert client.get(step(draft.pk, "class")).status_code == 404
    assert client.get(f"/characters/{draft.pk}/").status_code == 404
    client.force_login(alice)
    assert "Secret draft" in client.get("/characters/").content.decode()


def test_a_step_that_needs_an_earlier_one_redirects_to_it(signed_in, alice):
    draft = creation.start_draft(alice, "x")

    response = signed_in.get(step(draft.pk, "abilities"))

    assert response.status_code == 302 and response.url == step(draft.pk, "background")
    assert signed_in.get(step(draft.pk, "choices")).url == step(draft.pk, "class")
    assert signed_in.get(step(draft.pk, "nonsense")).status_code == 404


# --- the whole wizard over HTTP -------------------------------------------


def test_a_fighter_created_entirely_through_the_forms(signed_in, alice):
    pk = signed_in.post("/characters/new/", {"name": "Brienne"}).url.split("/")[2]

    def submit(name, data, expect=None):
        response = signed_in.post(step(pk, name), data)
        assert response.status_code == 302, response.content.decode()[:2000]
        assert response.url == (expect or step(pk, _after(name)))
        return response

    def _after(name):
        order = [
            "class",
            "background",
            "species",
            "languages",
            "equipment",
            "abilities",
            "choices",
            "alignment",
            "details",
            "review",
        ]
        return order[order.index(name) + 1]

    submit("class", {"class": "fighter"})
    # Choosing a background re-renders (its sub-choices depend on it) instead of moving on.
    assert signed_in.post(step(pk, "background"), {"background": "soldier"}).status_code == 200
    submit("background", {"background": "soldier", "background.tool": "dice-set"})
    assert signed_in.post(step(pk, "species"), {"species": "dwarf"}).status_code == 200
    submit("species", {"species": "dwarf"})
    submit("languages", {"action": "save", "languages": ["elvish", "goblin"]})
    submit("equipment", {"equipment.class": "A", "equipment.background": "A"})
    submit(
        "abilities",
        {
            "action": "save",
            "method": "standard",
            "base.str": 15,
            "base.dex": 14,
            "base.con": 13,
            "base.int": 8,
            "base.wis": 10,
            "base.cha": 12,
            "bonus.str": 2,
            "bonus.dex": 1,
        },
    )
    page = signed_in.get(step(pk, "choices")).content.decode()
    assert "Weapon Mastery" in page and "Fighting Style" in page
    from apps.builder.services import class_choices
    from apps.builder.services.store import Draft

    picks = {}
    for picker in class_choices.pickers(Draft(Character.objects.get(pk=pk))):
        chosen = [c[0] for c in picker.candidates][: picker.count]
        picks[picker.key] = chosen[0] if picker.single else chosen
    submit("choices", picks)
    submit("alignment", {"alignment": "LG"})
    submit("details", {"appearance": "Tall", "backstory.0": "A large family", "notes": ""})

    review = signed_in.get(step(pk, "review"))
    assert review.status_code == 200 and "Armor Class" in review.content.decode()
    finish = signed_in.post(f"/characters/{pk}/create/finish/")
    assert finish.status_code == 302 and finish.url == f"/characters/?new={pk}"

    character = Character.objects.get(pk=pk)
    assert character.status == Character.STATUS_COMPLETE and character.owner == alice
    assert character.alignment == "LG" and character.appearance == "Tall"
    page = signed_in.get(f"/characters/{pk}/").content.decode()
    assert "Brienne" in page and "Dungeoneer" in page  # the pack shows as one expandable line


def test_an_invalid_class_is_rejected_with_a_message(signed_in, alice):
    draft = creation.start_draft(alice, "x")

    response = signed_in.post(step(draft.pk, "class"), {"class": "jedi"})

    assert response.status_code == 200 and "Unknown" in response.content.decode()


def test_finish_is_refused_until_everything_is_done(signed_in, alice):
    draft = creation.start_draft(alice, "x")

    response = signed_in.post(f"/characters/{draft.pk}/create/finish/")

    assert response.status_code == 302 and response.url == step(draft.pk, "class")
    draft.refresh_from_db()
    assert draft.status == Character.STATUS_DRAFT


def test_discarding_deletes_only_your_own_draft(signed_in, alice, bob):
    mine = creation.start_draft(alice, "mine")
    theirs = creation.start_draft(bob, "theirs")

    assert signed_in.post(f"/characters/{theirs.pk}/create/discard/").status_code == 404
    assert signed_in.post(f"/characters/{mine.pk}/create/discard/").url == "/characters/"
    assert not Character.objects.filter(pk=mine.pk).exists()
    assert Character.objects.filter(pk=theirs.pk).exists()


# --- every screen renders ------------------------------------------------------------------------


@pytest.mark.parametrize("class_id", ["barbarian", "wizard", "cleric", "rogue", "warlock", "monk"])
def test_every_step_renders_for_a_finished_draft(signed_in, alice, class_id):
    character = build_character(alice, class_id, "acolyte", "elf")
    for name in [
        "class",
        "background",
        "species",
        "languages",
        "equipment",
        "abilities",
        "choices",
        "alignment",
        "details",
        "review",
    ]:
        response = signed_in.get(step(character.pk, name))
        assert response.status_code == 200, (class_id, name)
    state = creation.get_state(character)
    assert state["ready"]
    # The progress bar marks finished steps.
    assert 'class="complete' in signed_in.get(step(character.pk, "review")).content.decode()


def test_ability_step_methods_and_roll(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    from apps.builder.services import origins

    origins.select_class(draft, "fighter")
    origins.select_background(draft, "soldier")

    html = signed_in.get(step(draft.pk, "abilities")).content.decode()
    assert "Standard array" in html and "Point buy" in html
    signed_in.post(step(draft.pk, "abilities"), {"action": "method", "method": "pointbuy"})
    assert "27 points" in signed_in.get(step(draft.pk, "abilities")).content.decode()
    signed_in.post(step(draft.pk, "abilities"), {"action": "roll"})
    from apps.builder.services.store import Draft

    rolled = Draft(draft).get("abilities")["rolled"]
    assert len(rolled) == 6
    signed_in.post(step(draft.pk, "abilities"), {"action": "roll"})
    assert Draft(draft).get("abilities")["rolled"] == rolled  # never re-rolled


def test_review_adjustments_are_kept_and_can_be_undone(signed_in, alice):
    character = build_character(alice, "fighter")
    url = step(character.pk, "review")
    data = {
        "action": "adjust",
        "score.str": 3,
        "score.dex": 12,
        "score.con": 12,
        "score.int": 12,
        "score.wis": 12,
        "score.cha": 30,
    }
    data |= {f"skill.{s}": "none" for s in ["acrobatics"]}
    data["skill.arcana"] = "expertise"

    assert signed_in.post(url, data).status_code == 200
    character.refresh_from_db()
    assert (character.strength, character.charisma) == (3, 30)
    html = signed_in.get(url).content.decode()
    assert "manual" in html and "Undo all adjustments" in html
    assert character.proficiencies.get(category="skill", name="arcana").level == "expertise"

    signed_in.post(url, {"action": "reset"})
    character.refresh_from_db()
    assert character.strength != 3 and not character.proficiencies.filter(name="arcana").exists()

    bad = signed_in.post(url, {"action": "adjust", "score.str": 99})
    assert "1 to 30" in bad.content.decode()


def test_the_bottom_nav_keeps_characters_active_inside_the_wizard(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    html = signed_in.get(step(draft.pk, "class")).content.decode()
    assert 'data-menu="characters"' in html
    assert reverse("characters-overview") == "/characters/"


# --- Italian ---------------------------------------------------------------


def test_the_wizard_and_character_page_are_in_italian_and_metric(signed_in, alice):
    character = build_character(alice, "wizard", "acolyte", "elf")
    creation.finalize(character)
    signed_in.cookies["django_language"] = "it"

    page = signed_in.get(f"/characters/{character.pk}/").content.decode()

    assert "Classe Armatura" in page and "Punti ferita" in page and "Percezione passiva" in page
    assert "Armor Class" not in page
    assert " m<" in page or " m " in page  # speed in metres, not feet
    assert "ft." not in page
    listing = signed_in.get("/characters/").content.decode()
    assert "Personaggi" in listing and "Nuovo personaggio" in listing
    draft = creation.start_draft(alice, "x")
    step_page = signed_in.get(step(draft.pk, "class")).content.decode()
    assert "Ogni avventuriero è membro di una classe" in step_page and "Fasi" in step_page
    assert "Salva e continua" in step_page


def test_every_new_string_has_an_italian_translation():
    """Guards against adding UI text and forgetting the .po entry (msgfmt isn't always around)."""
    import gettext
    from pathlib import Path

    catalog = gettext.GNUTranslations(open("locale/it/LC_MESSAGES/django.mo", "rb"))._catalog
    for msgid in [
        "Save and continue",
        "Suggest for my class",
        "Undo all adjustments",
        "Lawful Good",
        "Weapon Mastery",
        "Ability scores",
        "Discard this character",
    ]:
        assert catalog.get(msgid), msgid
    assert Path("locale/it/LC_MESSAGES/django.po").read_text().count("msgid") > 260
