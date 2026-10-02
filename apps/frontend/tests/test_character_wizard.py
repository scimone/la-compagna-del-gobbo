"""The Characters menu and creation wizard, driven over HTTP like a browser would."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.builder.services import creation
from apps.builder.services.store import Draft
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


def test_list_is_public_and_only_admins_get_the_plus_button(client, alice, settings):
    response = client.get("/characters/")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="/characters/new/"' not in html and "No characters yet." in html

    settings.ADMIN_ACCOUNTS = ["alice"]
    client.force_login(alice)
    html = client.get("/characters/").content.decode()
    assert 'href="/characters/new/"' in html and "Tap + to create" in html


def test_only_admins_create_characters(client, alice, settings):
    client.force_login(alice)

    assert client.get("/characters/new/").status_code == 404
    assert client.post("/characters/new/", {"name": "Mira"}).status_code == 404
    assert not Character.objects.filter(name="Mira").exists()


def test_signed_out_plus_goes_to_sign_in_and_back(client, db):
    response = client.get("/characters/new/")

    assert response.status_code == 302
    assert response.url.startswith("/account/?next=/characters/new/")


def test_starting_a_character_creates_an_owned_draft_at_the_background_step(signed_in, alice, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
    response = signed_in.post("/characters/new/", {"name": "Mira"})

    character = Character.objects.get(name="Mira")
    assert character.owner == alice and character.status == Character.STATUS_DRAFT
    assert response.url == step(character.pk, "background")
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
    assert signed_in.get(step(draft.pk, "equipment")).url == step(draft.pk, "background")
    assert signed_in.get(step(draft.pk, "nonsense")).status_code == 404
    # The class's own choices are part of the class step now, not a step of their own.
    assert signed_in.get(step(draft.pk, "choices")).status_code == 404


# --- the whole wizard over HTTP -------------------------------------------


def test_a_fighter_created_entirely_through_the_forms(signed_in, alice, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
    pk = signed_in.post("/characters/new/", {"name": "Brienne"}).url.split("/")[2]

    def submit(name, data, expect=None):
        response = signed_in.post(step(pk, name), data)
        assert response.status_code == 302, response.content.decode()[:2000]
        assert response.url == (expect or step(pk, _after(name)))
        return response

    def _after(name):
        order = [
            "background",
            "class",
            "species",
            "languages",
            "equipment",
            "abilities",
            "alignment",
            "story",
            "review",
        ]
        return order[order.index(name) + 1]

    # Choosing a background re-renders (its sub-choices depend on it) instead of moving on.
    assert signed_in.post(step(pk, "background"), {"background": "soldier"}).status_code == 200
    submit("background", {"background": "soldier", "background.tool": "dice-set"})
    # Picking the class saves it and opens its level 1 choices right there (no step of their own).
    picked = signed_in.post(step(pk, "class"), {"class": "fighter", "action": "select"})
    assert picked.status_code == 200
    assert "Weapon Mastery" in picked.content.decode()
    from apps.builder.services import class_choices

    picks = {"class": "fighter"}
    for picker in class_choices.pickers(Draft(Character.objects.get(pk=pk))):
        chosen = [c[0] for c in picker.candidates][: picker.count]
        picks[picker.key] = chosen[0] if picker.single else chosen
    submit("class", picks)
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
    submit("alignment", {"alignment": "LG"})
    submit("story", {"backstory": "Raised on a farm, she left to serve the crown."})

    review = signed_in.get(step(pk, "review"))
    assert review.status_code == 200 and "Armor Class" in review.content.decode()
    finish = signed_in.post(f"/characters/{pk}/create/finish/")
    assert finish.status_code == 302 and finish.url == f"/characters/?new={pk}"

    character = Character.objects.get(pk=pk)
    assert character.status == Character.STATUS_COMPLETE and character.owner == alice
    assert character.alignment == "LG" and character.backstory.startswith("Raised on a farm")
    page = signed_in.get(f"/characters/{pk}/").content.decode()
    assert "Brienne" in page and "Dungeoneer" in page  # the pack shows as one expandable line


def test_an_invalid_class_is_rejected_with_a_message(signed_in, alice):
    draft = creation.start_draft(alice, "x")

    response = signed_in.post(step(draft.pk, "class"), {"class": "jedi"})

    assert response.status_code == 200 and "Unknown" in response.content.decode()


def test_finish_is_refused_until_everything_is_done(signed_in, alice):
    draft = creation.start_draft(alice, "x")

    response = signed_in.post(f"/characters/{draft.pk}/create/finish/")

    assert response.status_code == 302 and response.url == step(draft.pk, "background")
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
        "alignment",
        "story",
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


def test_the_wizard_and_character_page_are_in_italian_and_metric(signed_in, alice, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
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
    assert "Le sue scelte di 1º livello si aprono subito sotto" in step_page
    assert "Fasi" in step_page and "Storia del personaggio" in step_page
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


# --- live choices under the picked row, cards, descriptions, story -----------------

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def test_background_options_have_the_icon_vignette_like_the_world_list(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    from apps.builder.services import origins

    origins.select_class(draft, "fighter")

    background = signed_in.get(step(draft.pk, "background")).content.decode()
    assert 'class="thumb-vignette"' in background  # backgrounds get the soft edge...
    class_page = signed_in.get(step(draft.pk, "class")).content.decode()
    assert 'class="thumb-vignette"' not in class_page  # ...class art does not (as in the World)


def test_picking_a_row_opens_its_choices_right_under_it_without_pressing_next(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    from apps.builder.services import origins

    origins.select_class(draft, "fighter")

    response = signed_in.post(
        step(draft.pk, "background"), {"background": "guide", "action": "select"}, **AJAX
    )

    assert response.status_code == 200  # swapped in place, never a redirect to the next step
    html = response.content.decode()
    row = html[html.index('value="guide"') : html.index('class="actions"')]
    assert 'class="sub"' in row and "Magic Initiate (Druid): Cantrips" in row
    # Only the picked row has choices; the others are plain rows.
    assert html.count('class="sub"') == 1
    draft.refresh_from_db()
    assert Draft(draft).background.id == "guide"


def test_class_choices_live_under_the_class_not_in_a_later_step(signed_in, alice):
    draft = creation.start_draft(alice, "x")

    html = signed_in.post(
        step(draft.pk, "class"), {"class": "wizard", "action": "select"}, **AJAX
    ).content.decode()

    row = html[html.index('value="wizard"') : html.index('class="actions"')]
    assert 'class="sub"' in row
    for label in ("Skills", "Cantrips", "Spellbook", "Prepared spells"):
        assert label in row
    # Progress: there is no "Class features" step any more.
    assert "Class features" not in html and ">Background story<" in html


def test_a_refresh_saves_what_is_filled_in_and_shows_dependent_choices(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    from apps.builder.services import origins

    origins.select_class(draft, "wizard")
    picker = next(p for p in class_choices_pickers(draft) if p.key == "class.spellbook")
    book = [c[0] for c in picker.candidates][:6]

    html = signed_in.post(
        step(draft.pk, "class"),
        {"class": "wizard", "class.spellbook": book, "action": "refresh"},
        **AJAX,
    ).content.decode()

    assert Draft(draft).get("class.spellbook") == book
    # The prepared-spells picker now offers exactly the book's six spells.
    prepared = html[html.index('name="class.spells"') - 200 :]
    assert all(f'value="{spell}"' in prepared for spell in book)
    assert "still" not in html.lower() or "choose" in html.lower()  # no nagging mid-answer


def class_choices_pickers(character):
    from apps.builder.services import class_choices

    return class_choices.pickers(Draft(character))


def test_spells_are_cards_with_an_icon_properties_and_a_read_button(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    from apps.builder.services import origins

    origins.select_class(draft, "wizard")
    html = signed_in.get(step(draft.pk, "class")).content.decode()

    assert 'class="item-list compact-thumbs picks"' in html
    assert "/characters/describe/spell/fire-bolt/" in html
    assert "Cantrip · Evocation" in html  # the same properties line as the World's spell list
    assert "/static/images/spells/evocation.jpeg" in html
    assert html.count('class="pick-read"') > 20  # every candidate can be read


@pytest.mark.parametrize(
    ("kind", "pk", "expected"),
    [
        ("spell", "fire-bolt", ["Casting Time", "1d10", "Range"]),
        ("equipment", "thieves-tools", ["Cost", "Type", "Pick a lock"]),
        ("equipment", "greatsword", ["2d6", "Graze", "Mastery"]),
        ("feat", "defense", ["Fighting Style"]),
        ("invocation", "pact-of-the-blade", ["pact weapon"]),
        ("skill", "arcana", ["Intelligence"]),
    ],
)
def test_descriptions_can_be_read_for_every_kind_of_card(client, db, kind, pk, expected):
    response = client.get(f"/characters/describe/{kind}/{pk}/")

    assert response.status_code == 200
    html = response.content.decode()
    for text in expected:
        assert text in html, (kind, pk, text)


def test_describe_rejects_unknown_kinds_and_rows(client, db):
    assert client.get("/characters/describe/wizardry/x/").status_code == 404
    assert client.get("/characters/describe/spell/not-a-spell/").status_code == 404


def test_tools_are_cards_too(signed_in, alice):
    character = build_character(alice, "monk", "soldier", "human")
    html = signed_in.get(step(character.pk, "class")).content.decode()

    assert "/characters/describe/equipment/" in html  # Monk's artisan tool / instrument


def test_magic_initiate_names_its_list_and_only_offers_that_lists_spells(signed_in, alice):
    draft = creation.start_draft(alice, "x")
    from apps.builder.services import origins

    origins.select_class(draft, "fighter")
    origins.select_background(draft, "guide")
    html = signed_in.get(step(draft.pk, "background")).content.decode()

    assert "Magic Initiate (Druid): Cantrips" in html
    assert "The spells come from the Druid spell list." in html
    assert "/describe/spell/druidcraft/" in html
    assert "/describe/spell/blade-ward/" not in html  # a Wizard/Bard/Sorcerer/Warlock cantrip


def test_the_story_step_is_one_field_with_the_questions_as_a_guide(signed_in, alice):
    character = build_character(alice, "fighter")

    html = signed_in.get(step(character.pk, "story")).content.decode()

    assert html.count("<textarea") == 1 and 'name="backstory"' in html
    assert "Who is your family?" in html and "What in your past inspired you" in html
    assert "Background story" in html and "Appearance" not in html
    signed_in.post(step(character.pk, "story"), {"backstory": "Long ago, in a village..."})
    character.refresh_from_db()
    assert character.backstory == "Long ago, in a village..."


def test_a_later_background_removes_a_now_duplicate_class_skill_and_says_so(signed_in, alice):
    character = build_character(alice, "fighter", "soldier")
    from apps.rules.models import Background

    picked = set(Draft(character).get("class.skills"))
    other = next(b for b in Background.objects.all() if picked & {s.id for s in b.skills.all()})
    signed_in.post(
        step(character.pk, "background"), {"background": other.id, "action": "select"}, **AJAX
    )

    state = creation.get_state(character)
    assert {s["key"]: s["status"] for s in state["steps"]}["class"] == "incomplete"
    assert any(i["path"] == "class.skills" for s in state["steps"] for i in s["issues"])


def test_the_overview_row_separates_species_class_and_level_with_dots(signed_in, alice):
    from apps.builder.services import creation as _creation
    from apps.builder.tests.conftest import build_character

    character = build_character(alice, "wizard", "sage", "human", "Mira")
    _creation.finalize(character)

    html = signed_in.get("/characters/?view=list").content.decode()

    assert "Human · Wizard · Level 1" in html
    assert 'class="item-thumb pic-empty"' in html


# --- admins reopen a finished level-1 character ---------------------------------------------------


def test_admin_reopens_edits_and_finishes_keeping_inventory(client, alice, bob, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
    character = build_character(bob, "fighter")
    creation.finalize(character)
    character.refresh_from_db()
    character.experience_points = 120
    character.save()
    items_before = list(character.inventory_items.values_list("pk", flat=True))
    url = f"/characters/{character.pk}/reopen/"

    client.force_login(bob)
    assert client.post(url).status_code == 403

    client.force_login(alice)
    response = client.post(url)
    assert response.status_code == 302 and "/create/" in response.url
    character.refresh_from_db()
    assert character.status == Character.STATUS_DRAFT and creation.is_editing(character)
    # No way to throw the character away from the wizard while editing.
    assert client.post(f"/characters/{character.pk}/create/discard/").status_code == 302
    assert Character.objects.filter(pk=character.pk).exists()

    response = client.post(f"/characters/{character.pk}/create/finish/")
    assert response.url == f"/characters/{character.pk}/"
    character.refresh_from_db()
    assert character.status == Character.STATUS_COMPLETE and not creation.is_editing(character)
    assert character.experience_points == 120
    assert list(character.inventory_items.values_list("pk", flat=True)) == items_before


def test_a_leveled_character_cannot_be_reopened(client, alice, settings):
    settings.ADMIN_ACCOUNTS = ["alice"]
    character = build_character(alice, "fighter")
    creation.finalize(character)
    character.classes.update(level=2)

    client.force_login(alice)
    client.post(f"/characters/{character.pk}/reopen/")

    character.refresh_from_db()
    assert character.status == Character.STATUS_COMPLETE
