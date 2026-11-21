"""A finished character's page and the endpoint its script posts to, driven over HTTP."""

import json
import re
from io import BytesIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.html import escape
from PIL import Image

from apps.builder.services import creation, derived_stats, progression
from apps.builder.tests.conftest import build_character
from apps.characters.models import (
    Character,
    CharacterInventoryItem,
    CharacterOptionalFeature,
    CharacterSpell,
)
from apps.characters.services import play
from apps.conftest import default_campaign, make_dm
from apps.rules.models import Feat, Feature, OptionalFeature, Spell

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


def finished(owner, class_id, background="acolyte", species="human", name="Test"):
    character = build_character(owner, class_id, background, species, name)
    creation.finalize(character)
    character.refresh_from_db()
    return character


def act(client, character, **data):
    return client.post(f"/characters/{character.pk}/act/", data)


def panel(html: str, name: str) -> str:
    """The markup of one tab's panel (everything up to the next panel or the end of the page)."""
    chunks = html.split('role="tabpanel" data-panel="')[1:]
    for chunk in chunks:
        if chunk.startswith(f'{name}"'):
            return chunk
    raise AssertionError(f"no {name} panel")


# --- the page ----------------------------------------------------------------------------------


def test_the_top_holds_only_the_tab_strip(signed_in, alice):
    cleric = finished(alice, "cleric", name="Bruno")

    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()

    top = html[html.index('<div class="cs-top">') : html.index('role="tabpanel"')]
    assert "cs-name" not in top and "cs-pic" not in top and "Bruno" not in top
    tabbar = top.split('<div class="cs-tabbar">')[1]
    tabs = re.findall(r'<button type="button" role="tab" data-tab="(\w+)"', tabbar)
    assert tabs == [
        "stats",
        "abilities",
        "features",
        "spellbook",
        "inventory",
        "proficiencies",
        "biography",
    ]


def test_the_biography_tab_has_the_portrait_the_name_and_level_and_who_the_character_is(
    signed_in, alice
):
    cleric = finished(alice, "cleric", name="Bruno")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "biography")

    id_row = html.split('class="cs-identity"')[1].split("</section>")[0]
    assert 'class="cs-name"' in id_row and 'value="Bruno"' in id_row  # editable name...
    assert '<span class="cs-level">Level 1</span>' in id_row  # ...with the level next to it
    assert id_row.index('class="cs-pic"') < id_row.index('class="cs-who"')  # picture on the left
    for fact in ("Cleric", "Human", "Acolyte", "Medium"):
        assert fact in id_row
    # the numbers of the Stats tab are not here
    for gone in ("Armor Class", "Hit Points", "Death Saves", "Experience"):
        assert gone not in id_row


def test_a_multiclass_characters_class_line_lists_every_class_with_its_level(signed_in, alice):
    from apps.characters.models import CharacterClass
    from apps.rules.models import Class

    fighter = finished(alice, "fighter", background="soldier")
    CharacterClass.objects.create(character=fighter, klass=Class.objects.get(pk="wizard"), level=1)

    html = panel(signed_in.get(f"/characters/{fighter.pk}/").content.decode(), "biography")

    line = re.search(r'class="cs-class">(.*?)</span>\s*</div>', html, re.S).group(1)
    assert "Fighter</a> 1" in line and "Wizard</a> 1" in line and " / " in line


def test_the_stats_tab_holds_every_number_that_changes_during_play(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "stats")

    for card in (
        "Experience Points",
        "Armor Class",
        "Initiative",
        "Speed",
        "Passive Perception",
        "Hit Points",
        "Temp HP",
        "Heroic Inspiration",
        "Hit Dice",
        "Death Saves",
    ):
        assert card in html
    assert 'data-act="xp"' in html and "data-hp-open" in html
    assert html.count('data-death="successes"') == 1 and html.count('class="box ') == 6
    assert html.count('<div class="cs-scroll">') == 1


def test_the_stats_tab_reads_the_rests_then_hit_points_then_the_fight_numbers(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "stats")

    order = [
        html.index(name)
        for name in (
            "Short Rest",
            "Hit Points",
            "Armor Class",
            "Passive Perception",
            "Hit Dice",
            "Conditions",
            "Death Saves",
            "Experience Points",
        )
    ]
    assert order == sorted(order)
    # The cards flow in a plain grid (no height-weighted rows), so nothing can overlap.
    assert 'class="st-card st-hp st-wide"' in html and "cs-row" not in html
    assert 'class="st-card st-dice"' in html and 'class="st-card st-death"' in html
    # Exhaustion sits right on top of Conditions; hit points can be changed by any typed amount.
    assert html.index("st-card st-exh") < html.index("st-conds")
    page = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert 'id="cs-hp-dialog"' in page and all(
        f'data-hp-do="{k}"' in page for k in ("damage", "heal", "set")
    )


def test_the_stats_tab_shows_progress_bars_and_one_pip_per_hit_die(signed_in, alice, settings):
    make_dm(alice)  # only the DM (or an admin) sets Hit Dice by hand
    cleric = finished(alice, "cleric")
    act(signed_in, cleric, action="xp", value="150")
    act(signed_in, cleric, action="hp_delta", delta="-3")
    act(signed_in, cleric, action="hit_dice", die="d8", delta="1")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "stats")

    assert 'aria-valuenow="50"' in html  # 150 of the 300 XP the first level takes
    max_hp = cleric.max_hit_points
    assert f'data-hp-bar style="--pct: {round((max_hp - 3) / max_hp * 100)}%"' in html
    row = html.split('data-hd="d8"')[1].split("</div>")[0]
    assert row.count('class="pip-btn') == 1 and 'class="pip-btn on' not in row  # spent
    assert row.count('data-delta="-1"') == 1  # tapping the empty pip recovers the die


def test_hit_dice_pips_spend_and_recover_over_http(signed_in, alice, settings):
    make_dm(alice)  # only the DM (or an admin) sets Hit Dice by hand
    cleric = finished(alice, "cleric")

    spent = act(signed_in, cleric, action="hit_dice", die="d8", delta="1").json()
    back = act(signed_in, cleric, action="hit_dice", die="d8", delta="-1").json()

    assert spent["state"]["hit_dice"]["d8"] == {"total": 1, "spent": 1}
    assert back["state"]["hit_dice"]["d8"] == {"total": 1, "spent": 0}


def test_only_the_dm_or_an_admin_edits_hit_dice_by_hand(signed_in, alice, settings):
    cleric = finished(alice, "cleric")
    settings.ADMIN_ACCOUNTS = []

    assert act(signed_in, cleric, action="hit_dice", die="d8", delta="1").status_code == 403
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "stats")
    row = html.split('data-hd="d8"')[1].split("</div>")[0]
    assert " disabled" in row  # the pips are there to look at only


def test_reducing_the_maximum_and_a_score_works_and_a_long_rest_restores_them(signed_in, alice):
    cleric = finished(alice, "cleric")
    full = cleric.max_hit_points

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "stats")
    assert 'data-act="hp_max_reduction"' in html and 'data-ability="wis"' in html

    state = act(signed_in, cleric, action="hp_max_reduction", value="2").json()["state"]
    assert state["max_hp"] == full - 2
    assert (
        act(signed_in, cleric, action="ability_reduction", ability="wis", value="2").status_code
        == 200
    )
    assert (
        act(signed_in, cleric, action="ability_reduction", ability="xyz", value="2").status_code
        == 400
    )
    cleric.refresh_from_db()
    assert cleric.ability_reductions == {"wis": 2}

    act(signed_in, cleric, action="long_rest")
    cleric.refresh_from_db()
    assert cleric.ability_reductions == {} and cleric.max_hit_points_reduction == 0


def test_changing_the_xp_asks_for_a_redraw_so_the_progress_bar_follows(signed_in, alice):
    cleric = finished(alice, "cleric")

    assert act(signed_in, cleric, action="xp", value="10").json()["refresh"] is True


def test_what_must_stay_in_view_is_outside_the_scrolling_part_of_its_panel(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()

    assert html.count('<div class="cs-scroll">') == 7  # every panel scrolls on its own
    for tab, fixed in (
        ("abilities", "cs-pb"),  # the proficiency bonus is in the fixed part too...
        ("abilities", "cs-abilities"),
        ("spellbook", "cs-invbar"),
        ("inventory", "cs-purse"),
    ):
        before_scroll = panel(html, tab).split('<div class="cs-scroll">')[0]
        assert '<div class="cs-sticky">' in before_scroll and fixed in before_scroll
    fixed = panel(html, "abilities").split('<div class="cs-scroll">')[0]
    assert (
        '<div class="cs-subhead">' in fixed and "<h3>Skills</h3>" in fixed
    )  # heading stays in view
    assert "cs-legend" in fixed and "Not proficient" in fixed  # the legend sits next to it
    skills = panel(html, "abilities").split('<div class="cs-scroll">')[1]
    assert "cs-skills" in skills and "cs-abilities" not in skills and "cs-pb" not in skills
    assert "Skills</h3>" not in skills


def test_the_requested_tab_is_the_one_shown_first(signed_in, alice):
    cleric = finished(alice, "cleric")

    def hidden_panels(query):
        html = signed_in.get(f"/characters/{cleric.pk}/{query}").content.decode()
        return re.findall(r'data-panel="(\w+)" hidden', html)

    assert "spellbook" not in hidden_panels("?tab=spellbook") and "stats" in hidden_panels(
        "?tab=spellbook"
    )
    assert "stats" not in hidden_panels("?tab=nonsense")  # falls back to the first tab, Stats
    assert "stats" not in hidden_panels("")


def test_abilities_are_six_boxes_with_saves_and_the_skills_follow(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "abilities")

    assert html.count('class="cs-ab"') == 6
    saves = re.findall(r'<i class="pip( proficient)?"></i>\s*Save', html)
    assert len(saves) == 6 and saves.count(" proficient") == 2  # a cleric saves on Wis and Cha
    assert len(re.findall(r'<li>\s*<i class="pip ', html)) == 18
    assert '<span class="dim">DEX</span>' in html and '<span class="dim">dex</span>' not in html


def test_features_lists_species_traits_class_features_and_feats_as_clickable_links(
    signed_in, alice
):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "features")

    feature_list = html.split('id="cs-feature-list"')[1].split('id="cs-feature-empty"')[0]
    assert "Divine Order" in feature_list and "Magic Initiate" in feature_list
    # Rows link straight to each entry's own World page now, instead of unfolding inline - the
    # exact same `_list_item.html` markup the World's own Features list uses.
    assert 'href="/world/feats/feature/' in feature_list
    assert 'href="/world/feats/' in feature_list
    assert "data-describe=" not in feature_list
    assert 'name="type"' in html  # the type pills, once this character has more than one kind


def test_features_tab_has_no_bookmark_buttons(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "features")

    assert "item-bookmark" not in html and "bookmark-list" not in html


def test_options_are_mixed_into_features_with_their_own_page_icon(signed_in, alice):
    warlock = finished(alice, "warlock", background="charlatan")
    invocation = OptionalFeature.objects.filter(feature_type="Eldritch Invocation").first()
    CharacterOptionalFeature.objects.create(character=warlock, optional_feature=invocation)

    html = panel(signed_in.get(f"/characters/{warlock.pk}/").content.decode(), "features")
    feature_list = html.split('id="cs-feature-list"')[1].split('id="cs-feature-empty"')[0]
    row = next(chunk for chunk in feature_list.split("<li") if invocation.name in chunk)
    assert f'href="/world/feats/option/{invocation.pk}/"' in row
    assert "Option" in row  # the property tag, like "Feat"/"Class"/... for the others
    assert "features_classes/warlock.jpeg" in row  # a Warlock invocation uses the Warlock icon
    assert "data-describe=" not in row


def test_option_detail_page_shows_its_class_and_can_be_bookmarked(signed_in, alice):
    invocation = OptionalFeature.objects.filter(feature_type="Eldritch Invocation").first()

    html = signed_in.get(f"/world/feats/option/{invocation.pk}/").content.decode()

    assert invocation.name in html
    assert 'href="/world/classes/warlock/"' in html and "Warlock" in html
    assert 'id="bookmark-form"' in html


def test_subclass_feature_icons_get_a_distinguishing_border_class(signed_in, alice):
    html = signed_in.get("/world/feats/?type=subclass").content.decode()
    items = html.split('id="search-results"')[1]  # past <head>, where "<li" also matches "<link"

    assert "subclass-icon" in items
    row = next(chunk for chunk in items.split("<li") if "subclass-icon" in chunk)
    assert "features_subclasses/" in row


def test_spellbook_shows_the_casting_numbers_the_slots_and_the_spells(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")

    sticky = html.split('<div class="cs-sticky">')[1].split('<div class="cs-scroll">')[0]
    assert "data-casting-dc" not in sticky  # the casting numbers live on the stats tab now
    stats = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "stats")
    assert "data-casting-dc" not in stats  # the stats tab has no spellcasting card
    assert "My Spells" not in html
    assert 'name="q"' in sticky and "filter-popover" in sticky  # metrics, search and filters stick
    assert 'data-slot="1"' in html and html.count('class="pip-btn on"') == 2  # two 1st-level slots
    assert 'name="q"' in html and "filter-popover" in html  # the World's search and filters
    own = html.split('class="cs-sec cs-unprepared"')[0]
    assert (
        own.count("data-search=")
        == cleric.spells.filter(prepared=True).count()
        + cleric.spells.filter(prepared=False).exclude(spell__level__gt=0).count()
    )


def test_spellbook_rows_link_to_the_world_page_and_drop_the_level_filter(signed_in, alice):
    cleric = finished(alice, "cleric")
    known = cleric.spells.first().spell

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")

    assert f'href="/world/spells/{known.pk}/"' in html
    assert "data-describe=" not in html and 'class="chev"' not in html  # no toggle arrow
    assert "item-bookmark" not in html  # bookmarking lives in the World lists only
    tools = html.split('class="cs-spell-tools"')[1].split("</form>")[0]
    assert "Level" not in tools  # the level groups already group by it - redundant as a filter


def test_a_hand_added_spell_has_its_remove_button(signed_in, alice):
    cleric = finished(alice, "cleric")
    extra = Spell.objects.exclude(pk__in=cleric.spells.values_list("spell_id", flat=True)).first()
    act(signed_in, cleric, action="spell_add", spell=extra.pk)

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")

    row = next(chunk for chunk in html.split("<li") if f"/world/spells/{extra.pk}/" in chunk)
    assert 'class="item-remove"' in row


def test_spellbook_shows_the_prepared_count_and_toggles_preparation(signed_in, alice):
    cleric = finished(alice, "cleric")
    prepared = cleric.spells.filter(prepared=True, always_prepared=False, spell__level__gt=0)
    row = prepared.first()

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    header = html.split('class="cs-invbar"')[1].split("</div>")[0]
    assert f"Prepared <b>{prepared.count()}/" in header
    assert "after a long rest" in html

    # Locked until a long rest opens the window (SRD "Preparing Spells")...
    locked = act(signed_in, cleric, action="spell_prepare", spell=row.spell_id, prepared="0")
    assert locked.status_code == 400
    act(signed_in, cleric, action="long_rest")
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    assert "You can change any prepared spells now" in html
    # Told to unprepare first only when the class has no room for another prepared spell.
    full = prepared.count() >= derived_stats.compute(cleric).spellcasting[0]["prepared"]
    assert ("Unprepare a spell above to make room for another." in html) == full
    assert "Unprepare</button>" in html  # the prepared spells' buttons now offer to unprepare
    # ...and a Cleric may then change any number of them.
    act(signed_in, cleric, action="spell_prepare", spell=row.spell_id, prepared="0")
    row.refresh_from_db()
    assert not row.prepared


def test_spellbook_lists_the_rest_of_the_class_list_greyed_out_below_and_prepares_it(
    signed_in, alice
):
    cleric = finished(alice, "cleric")
    known = set(cleric.spells.values_list("spell_id", flat=True))

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")

    above, below = html.split('class="cs-sec cs-unprepared"')
    assert "Not prepared" in below and "<h3>Prepared</h3>" in above
    offered = Spell.objects.filter(level=1, classes__contains=["Cleric"]).exclude(pk__in=known)
    extra = offered.first()
    assert f"/world/spells/{extra.pk}/" in below and f"/world/spells/{extra.pk}/" not in above
    assert not Spell.objects.filter(pk__in=re.findall(r"/world/spells/([^/]+)/", below), level=0)
    assert f"Spells <b>{cleric.spells.count()}</b>" in html  # the offer is not "known"

    limit = derived_stats.compute(cleric).spellcasting[0]["prepared"]
    count = cleric.spells.filter(prepared=True, always_prepared=False, spell__level__gt=0).count()
    # A Prepare button only while the class has room for another spell.
    assert ("spell_prepare" in below) == (count < limit)

    # Make room (a level-1 cleric's list is full) - then preparing it creates the row.
    cleric.spells.filter(prepared=True, always_prepared=False, spell__level__gt=0).update(
        prepared=False
    )
    response = act(
        signed_in, cleric, action="spell_prepare", spell=extra.pk, prepared="1", klass="cleric"
    )
    assert response.status_code == 200
    assert cleric.spells.get(spell=extra).prepared
    assert cleric.spells.get(spell=extra).source == "class"

    # A spell that is not on the class's list is refused.
    other = Spell.objects.filter(level=1).exclude(classes__contains=["Cleric"]).first()
    refused = act(
        signed_in, cleric, action="spell_prepare", spell=other.pk, prepared="1", klass="cleric"
    )
    assert refused.status_code == 400
    assert not cleric.spells.filter(spell=other).exists()


def test_a_long_rest_asks_whether_to_change_the_prepared_spells(signed_in, alice):
    cleric = finished(alice, "cleric")

    response = act(signed_in, cleric, action="long_rest")

    (prompt,) = response.json()["prompts"]
    assert "prepared spells" in prompt["text"] and "can't change them until" in prompt["text"]
    fighter = finished(alice, "fighter", background="soldier")
    # A Fighter has no prepared spells to change, but may swap a Weapon Mastery weapon.
    (prompt,) = act(signed_in, fighter, action="long_rest").json()["prompts"]
    assert prompt["kind"] == "mastery" and prompt["tab"] == "proficiencies"
    assert "until your next long rest" in prompt["text"]


def test_cancelling_a_rests_offer_forfeits_that_change(signed_in, alice):
    cleric = finished(alice, "cleric")
    act(signed_in, cleric, action="long_rest")
    cleric.refresh_from_db()
    assert cleric.spell_changes
    assert act(signed_in, cleric, action="rest_decline", kind="spells").status_code == 200
    cleric.refresh_from_db()
    assert cleric.spell_changes == {}
    assert act(signed_in, cleric, action="rest_decline", kind="nonsense").status_code == 400

    fighter = finished(alice, "fighter", background="soldier")
    act(signed_in, fighter, action="long_rest")
    act(signed_in, fighter, action="rest_decline", kind="mastery")
    fighter.refresh_from_db()
    assert fighter.weapon_mastery_changes == {}


def test_a_hand_added_spell_of_a_preparing_class_follows_its_preparation(signed_in, alice):
    cleric = finished(alice, "cleric")
    cleric_spell = Spell.objects.filter(level=1, classes__contains=["Cleric"]).exclude(
        pk__in=list(cleric.spells.values_list("spell_id", flat=True))
    )
    cleric_spell = [cleric_spell.first()]
    free = Spell.objects.filter(level=1).exclude(classes__contains=["Cleric"]).first()
    act(signed_in, cleric, action="spell_add", spell=cleric_spell[0].pk)
    act(signed_in, cleric, action="spell_add", spell=free.pk)

    assert cleric.spells.get(spell=cleric_spell[0]).klass_id == "cleric"
    assert cleric.spells.get(spell=free).klass_id is None  # not on its list: just prepared
    assert cleric.spells.get(spell=free).prepared
    assert cleric.spells.get(spell=free).always_prepared  # off every list: nothing to swap it for
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    row = next(chunk for chunk in html.split("<li") if f"/world/spells/{free.pk}/" in chunk)
    assert "Always prepared" in row and "item-prepare" not in row


def test_cannot_prepare_more_spells_than_the_class_allows_nor_always_prepared_ones(
    signed_in, alice
):
    cleric = finished(alice, "cleric")
    always = cleric.spells.filter(always_prepared=True).first()
    if always:
        response = act(
            signed_in, cleric, action="spell_prepare", spell=always.spell_id, prepared="0"
        )
        assert response.status_code == 400
    klass = cleric.classes.first().klass
    extras = Spell.objects.filter(level=1).exclude(
        pk__in=cleric.spells.values_list("spell_id", flat=True)
    )[:10]
    for extra in extras:
        CharacterSpell.objects.create(character=cleric, spell=extra, klass=klass)
    statuses = [
        act(signed_in, cleric, action="spell_prepare", spell=e.pk, prepared="1").status_code
        for e in extras
    ]
    assert 200 in statuses and 400 in statuses  # prepared up to the class table's number, no more
    assert statuses == sorted(statuses)


def test_the_spellbooks_fixed_part_has_an_add_spell_button_even_without_spells(
    signed_in, client, alice, bob
):
    fighter = finished(alice, "fighter", background="soldier")
    assert not fighter.spells.exists()

    html = panel(signed_in.get(f"/characters/{fighter.pk}/").content.decode(), "spellbook")

    sticky = html.split('<div class="cs-sticky">')[1].split('<div class="cs-scroll">')[0]
    assert 'data-add-open="cs-add-spell"' in sticky and "Add spell" in sticky
    assert "Spells <b>0</b>" in sticky
    client.force_login(bob)
    theirs = panel(client.get(f"/characters/{fighter.pk}/").content.decode(), "spellbook")
    assert "data-add-open" not in theirs


def test_a_warlock_has_pact_slots(signed_in, alice):
    warlock = finished(alice, "warlock", background="charlatan")

    html = panel(signed_in.get(f"/characters/{warlock.pk}/").content.decode(), "spellbook")

    assert 'data-slot="pact"' in html and "Pact Magic" in html


def test_inventory_has_a_fixed_pouch_and_one_list_style_with_details_on_one_line(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")

    sticky = html.split('<div class="cs-sticky">')[1].split('<div class="cs-scroll">')[0]
    for coin in ("copper", "silver", "gold", "platinum"):
        assert f'data-coin="{coin}"' in sticky
    assert "data-add-open" in sticky and "Carrying" in sticky  # the toolbar is fixed too
    for section in ("Weapons", "Armor", "Misc Items"):
        assert f"<h3>{section}" in html
    assert "data-view" not in html and "Grid" not in html  # the list is the only layout
    mace = re.search(
        r'<div class="cs-line linked">\s*<a[^>]*href="/characters/\d+/inventory/\d+/"[^>]*>'
        r"\s*<span[^>]*>\s*<span[^>]*>Mace(.*?)</a>",
        html,
        re.S,
    )
    detail = re.search(r'class="item-detail">([^<]*)<', mace.group(1)).group(1)
    assert (
        detail.startswith("1d6") and "kg" in detail and "gp" in detail
    )  # one line: damage, weight, cost
    # A link to the item's page, no toggle arrow - like the Features and Spellbook rows - under
    # section headings that stay in view like the spellbook's.
    assert 'class="chev"' not in html and "data-describe=" not in html and "data-toggle" not in html
    assert 'id="cs-inventory"' in html and 'class="cs-level-head"' in html


def test_a_pack_is_not_listed_but_its_contents_are_and_say_where_they_came_from(signed_in, alice):
    cleric = finished(alice, "cleric")  # starts with a Priest's Pack
    pack = cleric.inventory_items.filter(contents__isnull=False).first()
    inside = pack.contents.select_related("equipment").first()

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")

    names = re.findall(r'<span class="item-name">([^<]*?)(?: <span|</span>)', html)
    assert escape(pack.equipment.name) not in names and escape(inside.equipment.name) in names
    row = html.split(f'data-key="catalog-{inside.pk}"')[1].split("</li>")[0]
    assert f"from {escape(pack.equipment.name)}" in row


def test_an_inventory_row_links_to_the_items_page_instead_of_unfolding_its_tools(signed_in, alice):
    cleric = finished(alice, "cleric")
    mace = cleric.inventory_items.get(equipment_id="mace")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")

    row = html.split(f'data-key="catalog-{mace.pk}"')[1].split("</li>")[0]
    assert f'href="/characters/{cleric.pk}/inventory/{mace.pk}/"' in row
    for tool in ('data-act="item_qty"', 'data-act="item_remove"'):
        assert tool not in html  # quantity and remove live on the item's own page now


def test_a_sellable_item_also_gets_a_quick_sell_button_right_on_its_row(signed_in, alice):
    cleric = finished(alice, "cleric")
    mace = cleric.inventory_items.get(equipment_id="mace")

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")

    row = html.split(f'data-key="catalog-{mace.pk}"')[1].split("</li>")[0]
    assert 'class="btn-sell-row"' in row and 'data-act="item_sell"' in row
    assert 'data-quantity="1"' in row and "data-confirm=" in row  # asks first, and says the price
    # The item's page still has its own "sell one" too (there's only one mace, so no "sell all") -
    # this doesn't replace it.
    page = signed_in.get(f"/characters/{cleric.pk}/inventory/{mace.pk}/").content.decode()
    assert "Sell one for" in page and "Sell all for" not in page


def test_a_stack_too_cheap_to_sell_one_of_still_gets_a_quick_sell_button_for_the_whole_stack(
    signed_in, alice
):
    # A single torch (1 cp) halves to 0 - nothing to sell one for - but ten of them are worth 5 cp.
    cleric = finished(alice, "cleric")
    torches = CharacterInventoryItem.objects.create(
        character=cleric, equipment_id="torch", quantity=10
    )

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")

    row = html.split(f'data-key="catalog-{torches.pk}"')[1].split("</li>")[0]
    assert 'class="btn-sell-row"' in row and 'data-quantity="10"' in row  # sells the whole stack
    page = signed_in.get(f"/characters/{cleric.pk}/inventory/{torches.pk}/").content.decode()
    assert "Sell one for" not in page and "Sell all for 5 cp" in page  # the page agrees


def test_a_monks_light_martial_weapons_are_listed_but_not_the_other_martial_ones(signed_in, alice):
    monk = finished(alice, "monk", background="guide", species="elf")

    html = panel(signed_in.get(f"/characters/{monk.pk}/").content.decode(), "proficiencies")

    assert "Simple weapons" in html and "Martial weapons with the Light property" in html
    weapons = html.split("<h3>Weapon Proficiencies</h3>")[1].split("<h3>Weapon Masteries</h3>")[0]
    assert "Shortsword" in weapons and "Scimitar" in weapons and "Dagger" in weapons
    assert "Greatsword" not in weapons and "Longsword" not in weapons


def test_a_fighters_weapon_masteries_and_tools_open_their_descriptions(signed_in, alice):
    fighter = finished(alice, "fighter", background="soldier")

    html = panel(signed_in.get(f"/characters/{fighter.pk}/").content.decode(), "proficiencies")

    masteries = html.split("<h3>Weapon Masteries</h3>")[1].split("<h3>")[0]
    assert len(re.findall(r'data-describe="/characters/describe/mastery/', masteries)) == 3
    assert "Gaming Sets" in html and "Languages" in html
    for url in re.findall(r'data-describe="(/characters/describe/[^"]+)"', masteries):
        assert signed_in.get(url).status_code == 200


def test_tools_are_one_section_called_tool_proficiencies_and_there_is_no_other_tools(
    signed_in, alice
):
    from apps.characters.models import CharacterProficiency

    rogue = finished(alice, "rogue")
    CharacterProficiency.objects.get_or_create(
        character=rogue, category="tool", name="thieves-tools"
    )

    html = panel(signed_in.get(f"/characters/{rogue.pk}/").content.decode(), "proficiencies")

    assert "<h3>Tool Proficiencies</h3>" in html
    assert "Artisan&#x27;s Tools" not in html and "Other Tools" not in html
    tools = html.split("<h3>Tool Proficiencies</h3>")[1].split("<h3>")[0]
    assert "Thieves&#x27; Tools" in tools  # what used to be under "Other Tools" is not lost


def test_describe_serves_features_and_masteries(signed_in, alice):
    cleric = finished(alice, "cleric")
    feature = cleric.features.first().feature

    assert signed_in.get(f"/characters/describe/feature/{feature.pk}/").status_code == 200
    assert signed_in.get("/characters/describe/mastery/sap/").status_code == 200
    assert signed_in.get("/characters/describe/feature/0/").status_code == 404


def test_biography_has_who_the_character_is_the_alignment_and_the_backstory_to_edit(
    client, alice, bob
):
    cleric = finished(alice, "cleric")
    cleric.backstory = "Raised by monks."
    cleric.save()

    client.force_login(bob)
    others = panel(client.get(f"/characters/{cleric.pk}/").content.decode(), "biography")
    assert "Raised by monks." in others and "<textarea" not in others
    assert "Alignment" in others
    for fact in ("Acolyte", "Cleric", "Human", "Medium"):
        assert fact in others  # class, species, background and size moved here from the header
    assert 'data-act="name"' not in others and "data-portrait-file" not in others  # read-only

    client.force_login(alice)
    mine = panel(client.get(f"/characters/{cleric.pk}/").content.decode(), "biography")
    assert '<textarea class="cs-text"' in mine and "Raised by monks." in mine
    assert mine.count("<textarea") == 1 and "Appearance" not in mine and "Notes" not in mine
    assert 'data-act="name"' in mine and "data-portrait-file" in mine  # the owner can edit both


def test_another_account_sees_the_sheet_without_any_controls(client, alice, bob):
    cleric = finished(alice, "cleric")
    client.force_login(bob)

    html = client.get(f"/characters/{cleric.pk}/").content.decode()

    assert 'data-act="hp_delta"' not in html and 'data-act="name"' not in html
    for control in re.findall(r'<button[^>]*data-act="(?:hit_dice|death_toggle)"[^>]*>', html):
        assert " disabled" in control  # the pips and boxes are there to look at only
    assert "by alice" in html and "data-portrait-file" not in html
    assert "cs-name" in html and "Level 1" in html


def test_the_sheet_is_in_italian_and_metric(signed_in, alice):
    cleric = finished(alice, "cleric")
    signed_in.cookies["django_language"] = "it"

    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()

    for word in ("Ispirazione eroica", "Dadi Vita", "Tiri salvezza", "Privilegi"):
        assert word in html
    for word in ("Statistiche", "Punti esperienza", "Cambia immagine"):
        assert word in html
    assert "Caratteristiche" in html and "ft." not in html


def test_a_draft_is_not_a_sheet(signed_in, alice):
    draft = creation.start_draft(alice, "Wip", default_campaign())

    assert signed_in.get(f"/characters/{draft.pk}/").status_code == 302


# --- the endpoint ------------------------------------------------------------------------------


def test_only_the_owner_may_post_changes(client, alice, bob):
    cleric = finished(alice, "cleric")

    assert act(client, cleric, action="inspiration", value="1").status_code == 403  # signed out
    client.force_login(bob)
    assert act(client, cleric, action="inspiration", value="1").status_code == 403
    cleric.refresh_from_db()
    assert cleric.inspiration is False


def test_a_draft_cannot_be_changed_through_the_sheet(signed_in, alice):
    draft = creation.start_draft(alice, "Wip", default_campaign())

    assert act(signed_in, draft, action="xp", value="10").status_code == 403


def test_hit_points_death_saves_inspiration_and_xp(signed_in, alice):
    cleric = finished(alice, "cleric")

    response = act(signed_in, cleric, action="hp_delta", delta="-3")
    assert (
        response.status_code == 200 and response.json()["state"]["hp"] == cleric.max_hit_points - 3
    )
    assert act(signed_in, cleric, action="hp_set", value="1").json()["state"]["hp"] == 1
    assert act(signed_in, cleric, action="temp_hp", value="4").json()["state"]["temp_hp"] == 4
    state = act(signed_in, cleric, action="hp_delta", delta="-2").json()["state"]
    assert (state["temp_hp"], state["hp"]) == (2, 1)  # temporary hit points took the damage
    state = act(signed_in, cleric, action="death_toggle", kind="failures", index="2").json()[
        "state"
    ]
    assert state["death_failures"] == 2
    assert act(signed_in, cleric, action="inspiration", value="1").json()["state"]["inspiration"]
    assert act(signed_in, cleric, action="xp", value="350").json()["state"]["xp"] == 350
    cleric.refresh_from_db()
    assert (cleric.death_save_failures, cleric.inspiration) == (2, True)


def test_hit_dice_are_spent_and_recovered_within_the_pool(signed_in, alice, settings):
    make_dm(alice)  # only the DM (or an admin) sets Hit Dice by hand
    fighter = finished(alice, "fighter", background="soldier")

    spent = act(signed_in, fighter, action="hit_dice", die="d10", delta="1").json()["state"]
    assert spent["hit_dice"]["d10"] == {"total": 1, "spent": 1}
    again = act(signed_in, fighter, action="hit_dice", die="d10", delta="1").json()["state"]
    assert again["hit_dice"]["d10"]["spent"] == 1  # only one die to spend
    back = act(signed_in, fighter, action="hit_dice", die="d10", delta="-1").json()["state"]
    assert back["hit_dice"]["d10"]["spent"] == 0
    assert act(signed_in, fighter, action="hit_dice", die="d20", delta="1").status_code == 400


def test_spell_slots_are_spent_and_recovered(signed_in, alice, settings):
    make_dm(alice)  # only the DM (or an admin) moves slots by hand
    wizard = finished(alice, "wizard", background="sage", species="elf")

    state = act(signed_in, wizard, action="slots", key="1", delta="1").json()["state"]
    assert state["slots"]["1"] == {"max": 2, "spent": 1}
    act(signed_in, wizard, action="slots", key="1", delta="1")
    assert (
        act(signed_in, wizard, action="slots", key="1", delta="1").json()["state"]["slots"]["1"][
            "spent"
        ]
        == 2
    )  # never more than the character has
    assert (
        act(signed_in, wizard, action="slots", key="1", delta="-1").json()["state"]["slots"]["1"][
            "spent"
        ]
        == 1
    )
    assert (
        act(signed_in, wizard, action="slots", key="7", delta="1").json()["state"]["slots"].get("7")
        is None
    )  # no 7th-level slots: nothing stored
    html = panel(signed_in.get(f"/characters/{wizard.pk}/").content.decode(), "spellbook")
    assert html.count('class="pip-btn on"') == 1  # the page draws the saved state


def test_only_the_dm_or_an_admin_edits_spell_slots_by_hand(signed_in, alice, settings):
    wizard = finished(alice, "wizard", background="sage", species="elf")
    settings.ADMIN_ACCOUNTS = []

    assert act(signed_in, wizard, action="slots", key="1", delta="1").status_code == 403
    html = panel(signed_in.get(f"/characters/{wizard.pk}/").content.decode(), "spellbook")
    row = html.split('data-slot="1"')[1].split("</div>")[0]
    assert "pip-btn" in row and " disabled" in row  # the pips are there to look at only


def test_the_shield_toggle_changes_ac_and_asks_for_a_redraw(signed_in, alice):
    cleric = finished(alice, "cleric")
    shield = cleric.inventory_items.get(equipment_id="shield")
    assert shield.equipped

    response = act(signed_in, cleric, action="equip", item=str(shield.pk), value="0")

    assert response.json()["refresh"] is True
    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert re.search(r'data-bind="ac">12<', html)  # chain shirt 13 - 1 Dex, without the shield's +2
    act(signed_in, cleric, action="equip", item=str(shield.pk), value="1")
    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert re.search(r'data-bind="ac">14<', html)


def test_equipping_armor_that_is_not_yours_or_not_wearable_is_refused(signed_in, alice):
    cleric = finished(alice, "cleric")
    other = finished(alice, "wizard", background="sage", species="elf", name="Other")
    theirs = other.inventory_items.first()
    rope = CharacterInventoryItem.objects.create(character=cleric, equipment_id="rope", quantity=1)

    assert act(signed_in, cleric, action="equip", item=str(theirs.pk), value="1").status_code == 400
    assert act(signed_in, cleric, action="equip", item=str(rope.pk), value="1").status_code == 400


def test_coins_name_and_text_are_saved(signed_in, alice):
    cleric = finished(alice, "cleric")

    state = act(signed_in, cleric, action="coin", coin="platinum", value="3").json()["state"]
    assert state["coins"]["platinum"] == 3
    assert act(signed_in, cleric, action="name", value="Brother Bruno").json()["state"]["name"] == (
        "Brother Bruno"
    )
    act(signed_in, cleric, action="text", field="backstory", value="Owes the innkeeper 5 gp.")
    cleric.refresh_from_db()
    assert cleric.backstory == "Owes the innkeeper 5 gp." and cleric.name == "Brother Bruno"
    assert act(signed_in, cleric, action="name", value=" ").status_code == 400


def test_bad_requests_are_refused_without_changing_anything(signed_in, alice):
    cleric = finished(alice, "cleric")
    before = Character.objects.values().get(pk=cleric.pk)

    assert act(signed_in, cleric, action="teleport").status_code == 400
    assert act(signed_in, cleric, action="hp_delta", delta="lots").status_code == 400
    assert act(signed_in, cleric, action="coin", coin="doubloons", value="1").status_code == 400
    assert act(signed_in, cleric, action="text", field="owner", value="1").status_code == 400
    assert act(signed_in, cleric, action="text", field="notes", value="x").status_code == 400
    assert signed_in.get(f"/characters/{cleric.pk}/act/").status_code == 405

    after = Character.objects.values().get(pk=cleric.pk)
    assert after == before


# --- items ---------------------------------------------------------------------------------------


def test_adding_a_catalog_item_stacks_and_says_what_was_added(signed_in, alice):
    cleric = finished(alice, "cleric")

    first = act(signed_in, cleric, action="item_add", equipment="longsword").json()
    act(signed_in, cleric, action="item_add", equipment="longsword")

    assert first["refresh"] is True and first["message"] == "Added Longsword"
    assert cleric.inventory_items.get(equipment_id="longsword", parent=None).quantity == 2
    assert act(signed_in, cleric, action="item_add", equipment="nope").status_code == 400


def test_buying_a_catalog_item_pays_for_it_out_of_the_purse(signed_in, alice):
    from apps.rules.models import Equipment

    cleric = finished(alice, "cleric")
    cleric.currency.gold, cleric.currency.silver, cleric.currency.copper = 20, 0, 0
    cleric.currency.save()
    price = Equipment.objects.get(pk="longsword").value  # 15 gp, in copper

    response = act(signed_in, cleric, action="item_buy", equipment="longsword")

    assert response.status_code == 200 and response.json()["refresh"] is True
    assert response.json()["message"] == "Bought Longsword for 15 gp"
    cleric.currency.refresh_from_db()
    assert cleric.currency.gold * 100 + cleric.currency.silver * 10 + cleric.currency.copper == (
        2000 - price
    )
    assert cleric.inventory_items.get(equipment_id="longsword", parent=None).quantity == 1


def test_buying_without_enough_money_is_refused_and_nothing_changes(signed_in, alice):
    cleric = finished(alice, "cleric")
    cleric.currency.gold = cleric.currency.silver = cleric.currency.copper = 0
    cleric.currency.save()

    response = act(signed_in, cleric, action="item_buy", equipment="longsword")

    assert response.status_code == 400
    cleric.currency.refresh_from_db()
    assert (cleric.currency.gold, cleric.currency.silver, cleric.currency.copper) == (0, 0, 0)
    assert not cleric.inventory_items.filter(equipment_id="longsword").exists()
    # An item with no price at all cannot be bought either.
    free = cleric.inventory_items.exclude(equipment__value__gt=0).first()
    if free:
        assert (
            act(signed_in, cleric, action="item_buy", equipment=free.equipment_id).status_code
            == 400
        )


def test_only_the_owner_buys_items(signed_in, client, alice, bob):
    cleric = finished(alice, "cleric")
    client.force_login(bob)

    assert act(client, cleric, action="item_buy", equipment="longsword").status_code == 403
    assert not cleric.inventory_items.filter(equipment_id="longsword").exists()


def test_the_add_item_sheets_purse_and_buy_buttons_are_visible_without_opening_a_row(
    signed_in, alice
):
    cleric = finished(alice, "cleric")
    cleric.currency.gold = 100
    cleric.currency.save()

    html = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()

    purse = html.split('<div class="cs-purse"')[1].split("</div>")[0]
    assert 'data-bind="coins.gold"' in purse and ">100<" in purse
    row = html.split('data-equipment="longsword"')[0]
    assert 'data-act="item_buy"' in row.rsplit("<li ", 1)[-1] or 'data-act="item_buy"' in html


def test_the_add_overlays_have_their_own_language_switch(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()

    assert html.count('class="lang-switcher"') == 4  # base.html's own, plus one per overlay
    for overlay_id in ("cs-add", "cs-add-spell", "cs-add-feature"):
        head = html.split(f'id="{overlay_id}"')[1].split("cs-overlay-body")[0]
        assert "lang-switcher" in head and "Italiano" in head
    assert act(signed_in, cleric, action="item_add", equipment="nope").status_code == 400


def test_a_custom_item_is_listed_in_its_section_and_sold_at_its_own_price(signed_in, alice):
    cleric = finished(alice, "cleric")
    gold_before = cleric.currency.gold

    response = act(
        signed_in, cleric, action="custom_add", name="Ruby", section="misc", type="Gemstone",
        quantity="2", weight="0.5", cost="50", valuable="1", description="Blood red.",
    )  # fmt: skip

    assert response.status_code == 200 and response.json()["message"] == "Added Ruby"
    ruby = cleric.custom_items.get()
    assert (ruby.quantity, ruby.weight, ruby.value, ruby.valuable) == (2, 1.0, 5000, True)  # 0.5 kg
    assert ruby.type_label == "Gemstone"
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")
    assert "Ruby" in html and "Gemstone" in html  # the type is in the detail line
    page = signed_in.get(f"/characters/{cleric.pk}/inventory/custom/{ruby.pk}/").content.decode()
    assert "Blood red." in page  # what the player wrote is on the item's own page
    assert "Trade goods and valuables sell for their full value." in page

    sold = act(
        signed_in, cleric, action="item_sell", kind="custom", item=str(ruby.pk), quantity="1"
    )
    assert sold.json()["message"] == "Sold for 50 gp"  # a valuable: the full 50 gp, not 25
    cleric.currency.refresh_from_db()
    assert cleric.currency.gold == gold_before + 50 and cleric.custom_items.get().quantity == 1


@pytest.mark.django_db
def test_class_subclasses_start_collapsed_and_share_one_exclusive_group(client, imported_rules):
    html = client.get("/world/classes/cleric/?tab=subclasses").content.decode()

    blocks = re.findall(r'<details class="subclass-block"[^>]*>', html)
    assert blocks and all(
        tag == '<details class="subclass-block" name="subclass">' for tag in blocks
    )


@pytest.mark.django_db
def test_class_levels_tab_has_plain_headings_and_subclass_headings_are_sticky(
    client, imported_rules
):
    html = client.get("/world/classes/cleric/?tab=levels").content.decode()
    assert '<div class="level-heading">Level 1</div>' in html
    assert '<details class="level-group"' not in html  # no toggle on a level heading

    detail = Path("apps/frontend/templates/frontend/detail.html").read_text()
    subclass_rule = detail.split(".subclass-block > summary {")[1].split("}")[0]
    assert "position: sticky" in subclass_rule


@pytest.mark.django_db
def test_world_features_list_leaves_out_ability_score_improvement(client, imported_rules):
    assert Feature.objects.filter(name_en="Ability Score Improvement").exists()

    classes = client.get("/world/feats/?type=class").content.decode()
    everything = client.get("/world/feats/").content.decode()

    assert "Ability Score Improvement" not in classes
    # the General *feat* of the same name is a different thing, and stays
    assert "Ability Score Improvement" in everything
    assert not re.search(r"Ability Score Improvement</span>\s*<div[^>]*>Class", everything)


def test_a_custom_item_can_be_bought_out_of_the_purse_or_just_added(signed_in, alice):
    cleric = finished(alice, "cleric")
    play.set_coin(cleric, "gold", 100)

    bought = act(
        signed_in, cleric, action="custom_add", name="Spyglass", cost="30", quantity="2", buy="1"
    )

    assert bought.status_code == 200
    assert bought.json()["message"] == "Bought Spyglass for 60 gp"
    cleric.currency.refresh_from_db()
    assert cleric.currency.gold == 40 and cleric.custom_items.get().quantity == 2

    gift = act(signed_in, cleric, action="custom_add", name="Gift", cost="30")  # no `buy`
    assert gift.json()["message"] == "Added Gift"
    cleric.currency.refresh_from_db()
    assert cleric.currency.gold == 40  # nothing paid


def test_buying_a_custom_item_needs_a_cost_and_enough_money(signed_in, alice):
    cleric = finished(alice, "cleric")
    play.set_coin(cleric, "gold", 10)

    broke = act(signed_in, cleric, action="custom_add", name="Anvil", cost="50", buy="1")
    free = act(signed_in, cleric, action="custom_add", name="Pebble", buy="1")

    assert broke.status_code == 400 and free.status_code == 400
    cleric.currency.refresh_from_db()
    assert cleric.currency.gold == 10 and not cleric.custom_items.exists()


def test_a_custom_weapon_can_carry_a_simple_or_martial_category(signed_in, alice):
    cleric = finished(alice, "cleric")

    act(
        signed_in, cleric, action="custom_add", name="Boomerang", section="weapons",
        type="Ranged Weapon", weapon_category="martial",
    )  # fmt: skip

    boomerang = cleric.custom_items.get()
    assert boomerang.weapon_category == "martial"
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")
    assert "Martial" in html and "Ranged Weapon" in html  # both in the detail line

    # A non-weapon section drops the field rather than trust it, and an unknown value is rejected.
    reply = act(signed_in, cleric, action="custom_add", name="Trinket", weapon_category="martial")
    assert reply.status_code == 200
    assert cleric.custom_items.get(name="Trinket").weapon_category == ""
    assert (
        act(
            signed_in, cleric, action="custom_add", name="x", section="weapons",
            weapon_category="deadly",
        ).status_code == 400
    )  # fmt: skip


def test_a_custom_item_needs_a_name_and_sane_numbers(signed_in, alice):
    cleric = finished(alice, "cleric")

    assert act(signed_in, cleric, action="custom_add", name=" ").status_code == 400
    assert act(signed_in, cleric, action="custom_add", name="x", cost="cheap").status_code == 400
    assert act(signed_in, cleric, action="custom_add", name="x", section="ship").status_code == 400
    assert not cleric.custom_items.exists()


def test_custom_weight_is_typed_in_kilograms_on_the_italian_site(signed_in, alice):
    cleric = finished(alice, "cleric")
    signed_in.cookies["django_language"] = "it"

    act(signed_in, cleric, action="custom_add", name="Sasso", weight="1,5")

    assert cleric.custom_items.get().weight == 3.0  # 1.5 kg is 3 lb
    assert "Peso (kg)" in signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()


def test_quantity_removal_and_selling_over_http(signed_in, alice):
    cleric = finished(alice, "cleric")
    mace = cleric.inventory_items.get(equipment_id="mace")

    args = {"kind": "catalog", "item": str(mace.pk)}
    assert act(signed_in, cleric, action="item_qty", value="3", **args).status_code == 200
    assert act(signed_in, cleric, action="item_qty", delta="-9", **args).status_code == 200
    mace.refresh_from_db()
    assert mace.quantity == 1  # never below one
    sold = act(signed_in, cleric, action="item_sell", quantity="1", **args).json()
    assert sold["message"] == "Sold for 2 gp 5 sp"  # half of a mace's 5 gp
    assert not cleric.inventory_items.filter(pk=mace.pk).exists()
    gone = act(signed_in, cleric, action="item_remove", **args)
    assert gone.status_code == 400  # it is already gone
    assert act(signed_in, cleric, action="item_sell", kind="boat", item="1").status_code == 400


def test_removing_and_selling_only_touch_the_owners_own_items(signed_in, client, alice, bob):
    cleric = finished(alice, "cleric")
    stack = cleric.inventory_items.get(equipment_id="mace")
    client.force_login(bob)

    for action in ("item_remove", "item_sell", "item_qty", "item_add", "custom_add"):
        response = act(client, cleric, action=action, kind="catalog", item=str(stack.pk), value="2")
        assert response.status_code == 403
    assert cleric.inventory_items.filter(pk=stack.pk).exists()


def test_the_add_item_sheet_lists_the_whole_catalog_with_filters_and_a_custom_form(
    signed_in, alice
):
    from apps.rules.models import Equipment

    cleric = finished(alice, "cleric")

    html = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()

    assert html.count('data-act="item_add"') == Equipment.objects.count()  # one Add each...
    assert (
        0 < html.count('data-act="item_buy"') < Equipment.objects.count()
    )  # ...and Buy where priced
    assert 'name="q"' in html and "filter-popover" in html  # the World's search + filters
    for label in ("Category", "Properties", "Mastery"):
        assert label in html  # a filter button each
    assert "data-custom-form" in html and 'name="valuable"' in html and 'name="type"' in html
    assert 'data-category="martial"' in html and 'data-mastery="sap"' in html
    assert "Carrying" not in html  # (that's the inventory tab's own toolbar)
    for coin in ("copper", "silver", "gold", "platinum"):
        assert f'data-bind="coins.{coin}"' in html  # the purse is sticky on top


def test_the_add_item_sheet_starts_with_pills_for_the_main_type_and_the_rest_waits_for_one(
    signed_in, alice
):
    cleric = finished(alice, "cleric")

    html = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()
    # The custom-item form (also up in the fixed part, next to this) has its own Category pills,
    # also named "section" - scope to the World's own search+filters form for these asserts.
    catalog = html.split('<form class="world-search"')[1].split("</form>")[0]

    pills = re.findall(r'<input\s+type="radio"\s+name="section"\s+value="(\w*)"([^>]*)>', catalog)
    assert [value for value, _checked in pills] == ["", "weapons", "armor", "tools", "misc"]
    assert ["checked" in checked for _value, checked in pills] == [True, False, False, False, False]
    # The "Set" filter (Adventuring Gear, Ammunition, ...) is always there, whatever pill...
    filters = re.findall(r'<details class="filter-popover"([^>]*)>', catalog)
    always = [f for f in filters if "data-only=" not in f]
    assert len(always) == 1 and "hidden" not in always[0]
    assert "Adventuring Gear" in catalog.split("<summary")[1]
    # ...every other filter belongs to one pill and is hidden until it is picked,
    assert all("hidden" in f for f in filters if "data-only=" in f)
    # and only the weapons have the weapon-only ones.
    only = {
        label: re.findall(r'data-only="(\w+)"[^>]*>\s*<summary[^>]*>\s*' + label, catalog)
        for label in ("Category", "Properties", "Mastery", "Type")
    }
    assert only["Category"] == only["Properties"] == only["Mastery"] == ["weapons"]
    assert only["Type"] == []
    # Every row says which pill it belongs to (not the custom form's own markup: an item's own
    # `data-section` isn't the same attribute as a radio's `name="section"` above).
    assert 'data-section="weapons"' in html and 'data-section="armor"' in html
    assert 'data-section="tools"' in html and 'data-section="misc"' in html


def test_the_types_offered_under_a_pill_are_that_pills_own(signed_in, alice):
    cleric = finished(alice, "cleric")

    html = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()

    # The World's own list (not the sheet) keeps one Type filter per pill.
    html = signed_in.get("/world/items/").content.decode()
    armor = html.split('data-only="armor"')[1].split("</details>")[0]
    assert "Light Armor" in armor and "Heavy Armor" in armor and "Shield" in armor
    assert "Melee Weapon" not in armor and "Adventuring Gear" not in armor
    weapons = html.split('data-only="weapons"')[1].split("</details>")[0]
    assert "Melee Weapon" in weapons and "Ranged Weapon" in weapons


def test_the_add_spell_sheet_lists_every_spell_with_the_worlds_filters(signed_in, alice):
    from apps.rules.models import Spell

    cleric = finished(alice, "cleric")
    known = cleric.spells.first().spell

    html = signed_in.get(f"/characters/{cleric.pk}/spells/").content.decode()

    assert html.count('data-act="spell_add"') == Spell.objects.count()
    assert 'name="q"' in html and "filter-popover" in html
    for label in ("Level", "Class", "School", "Range", "Casting Time", "Saving Throw"):
        assert label in html  # a filter button each
    assert 'data-level="3"' in html and 'data-school="' in html and 'data-class="' in html
    row = html.split(f'data-spell="{known.pk}"')[1].split("</li>")[0]
    assert " disabled" in row.split(">")[0] and "Added" in row  # one it already has
    other = html.split('data-spell="fireball"')[1].split("</li>")[0]
    assert " disabled" not in other.split(">")[0]


def test_the_add_spell_sheet_is_for_the_owner_only(client, alice, bob):
    cleric = finished(alice, "cleric")

    assert client.get(f"/characters/{cleric.pk}/spells/").status_code == 403
    client.force_login(bob)
    assert client.get(f"/characters/{cleric.pk}/spells/").status_code == 403
    assert 'id="cs-add-spell"' not in client.get(f"/characters/{cleric.pk}/").content.decode()


def test_adding_and_removing_a_spell_over_http(signed_in, alice):
    cleric = finished(alice, "cleric")
    before = cleric.spells.count()

    added = act(signed_in, cleric, action="spell_add", spell="fireball")

    assert added.status_code == 200 and added.json()["refresh"] is True
    assert added.json()["message"] == "Added Fireball"
    assert cleric.spells.count() == before + 1
    assert act(signed_in, cleric, action="spell_add", spell="fireball").status_code == 400
    assert act(signed_in, cleric, action="spell_add", spell="nope").status_code == 400

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    assert html.count('data-act="spell_remove"') == 1  # only the one added by hand
    assert f"Spells <b>{before + 1}</b>" in html
    assert act(signed_in, cleric, action="spell_remove", spell="fireball").status_code == 200
    granted = cleric.spells.exclude(source="sheet").first()
    assert act(signed_in, cleric, action="spell_remove", spell=granted.spell_id).status_code == 400
    assert cleric.spells.count() == before


def test_only_the_owner_adds_or_removes_spells(signed_in, client, alice, bob):
    cleric = finished(alice, "cleric")
    client.force_login(bob)

    for action in ("spell_add", "spell_remove"):
        assert act(client, cleric, action=action, spell="fireball").status_code == 403
    assert not cleric.spells.filter(spell_id="fireball").exists()


def test_the_add_item_sheet_is_for_the_owner_only(client, alice, bob):
    cleric = finished(alice, "cleric")

    assert client.get(f"/characters/{cleric.pk}/items/").status_code == 403
    client.force_login(bob)
    assert client.get(f"/characters/{cleric.pk}/items/").status_code == 403
    page = client.get(f"/characters/{cleric.pk}/").content.decode()
    assert "data-add-open" not in page and 'id="cs-add"' not in page


# --- the portrait ------------------------------------------------------------------------------


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def upload(client, character, size=(300, 400), name="me.png", **extra):
    out = BytesIO()
    Image.new("RGB", size, "teal").save(out, "PNG")
    data = {"file": SimpleUploadedFile(name, out.getvalue()), **extra}
    return client.post(f"/characters/{character.pk}/portrait/", data)


def test_the_owner_uploads_a_portrait_and_everyone_sees_it_in_the_biography_tab(
    signed_in, client, media, alice, bob
):
    cleric = finished(alice, "cleric")
    before = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "biography")
    assert 'class="cs-pic"' in before and "<img" not in before

    response = upload(signed_in, cleric)

    assert response.status_code == 200 and response.json() == {"ok": True, "refresh": True}
    cleric.refresh_from_db()
    bio = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "biography")
    assert f'<img src="/characters/{cleric.pk}/portrait/?v={cleric.portrait.name}"' in bio
    assert "data-portrait-remove" in bio and "data-portrait-file" in bio

    picture = signed_in.get(f"/characters/{cleric.pk}/portrait/")
    assert picture.status_code == 200 and picture["Content-Type"] == "image/webp"
    assert picture.content[:4] == b"RIFF"

    client.force_login(bob)  # another account sees it, but has no way to change it
    theirs = panel(client.get(f"/characters/{cleric.pk}/").content.decode(), "biography")
    assert "<img" in theirs and "data-portrait-file" not in theirs
    assert client.get(f"/characters/{cleric.pk}/portrait/").status_code == 200


def test_the_avatar_frame_is_chosen_at_upload_and_changeable_later(
    signed_in, client, media, alice, bob
):
    cleric = finished(alice, "cleric")
    upload(signed_in, cleric, cx="0.3", cy="0.7", zoom="2.5")
    cleric.refresh_from_db()
    assert (cleric.portrait_cx, cleric.portrait_cy, cleric.portrait_zoom) == (0.3, 0.7, 2.5)
    bio = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "biography")
    assert (
        'data-zoom="2.500"' in bio and "data-portrait-open" in bio and "data-portrait-frame" in bio
    )

    # Only the frame changes: no new file, the picture stays.
    kept = cleric.portrait.name
    response = signed_in.post(
        f"/characters/{cleric.pk}/portrait/", {"cx": "0.9", "cy": "-3", "zoom": "99"}
    )
    cleric.refresh_from_db()
    assert response.status_code == 200 and cleric.portrait.name == kept
    assert (cleric.portrait_cx, cleric.portrait_cy, cleric.portrait_zoom) == (0.9, 0.0, 4.0)

    assert signed_in.post(f"/characters/{cleric.pk}/portrait/", {"zoom": "abc"}).status_code == 400
    client.force_login(bob)
    assert client.post(f"/characters/{cleric.pk}/portrait/", {"zoom": "2"}).status_code == 403


def test_without_a_portrait_there_is_nothing_to_serve(signed_in, alice):
    cleric = finished(alice, "cleric")

    assert signed_in.get(f"/characters/{cleric.pk}/portrait/").status_code == 404


def test_only_the_owner_changes_the_portrait(signed_in, client, media, alice, bob):
    cleric = finished(alice, "cleric")
    upload(signed_in, cleric)
    cleric.refresh_from_db()
    kept = cleric.portrait.name

    client.force_login(bob)
    assert upload(client, cleric).status_code == 403
    assert client.post(f"/characters/{cleric.pk}/portrait/", {"remove": "1"}).status_code == 403
    client.logout()
    assert upload(client, cleric).status_code == 403
    cleric.refresh_from_db()
    assert cleric.portrait.name == kept


def test_a_bad_upload_says_why_and_removing_goes_back_to_the_placeholder(signed_in, media, alice):
    cleric = finished(alice, "cleric")

    not_a_picture = signed_in.post(
        f"/characters/{cleric.pk}/portrait/",
        {"file": SimpleUploadedFile("me.png", b"<html>")},
    )
    nothing = signed_in.post(f"/characters/{cleric.pk}/portrait/", {})
    assert not_a_picture.status_code == 400 and "not a picture" in not_a_picture.json()["error"]
    assert nothing.status_code == 400 and not cleric.portrait

    upload(signed_in, cleric)
    removed = signed_in.post(f"/characters/{cleric.pk}/portrait/", {"remove": "1"})
    cleric.refresh_from_db()
    assert removed.status_code == 200 and not cleric.portrait
    assert signed_in.get(f"/characters/{cleric.pk}/portrait/").status_code == 404
    assert signed_in.put(f"/characters/{cleric.pk}/portrait/").status_code == 405


# --- adding and removing features -----------------------------------------------------------------


def test_the_features_tab_has_an_add_feature_button_even_without_features(
    signed_in, client, alice, bob
):
    fighter = finished(alice, "fighter", background="soldier")
    fighter.features.all().delete()
    fighter.feats.all().delete()

    html = panel(signed_in.get(f"/characters/{fighter.pk}/").content.decode(), "features")

    sticky = html.split('<div class="cs-sticky">')[1].split('<div class="cs-scroll">')[0]
    assert 'data-add-open="cs-add-feature"' in sticky and "Add feature" in sticky
    assert "No features yet." in html
    client.force_login(bob)
    theirs = panel(client.get(f"/characters/{fighter.pk}/").content.decode(), "features")
    assert "data-add-open" not in theirs


def test_the_add_feature_sheet_lists_the_catalog_with_a_type_pill_and_class_species_filters(
    signed_in, alice
):
    from apps.rules.models import Feat, OptionalFeature

    cleric = finished(alice, "cleric")
    known = cleric.features.first().feature

    html = signed_in.get(f"/characters/{cleric.pk}/features/").content.decode()

    assert (
        html.count('data-act="feature_add"')
        > Feat.objects.count() + OptionalFeature.objects.count()
    )
    assert 'name="q"' in html and 'name="type"' in html
    for kind in ("feat", "class", "subclass", "species", "option"):
        assert f'data-type="{kind}"' in html
    class_filter = html.split('data-only="class subclass option"')[1].split("</details>")[0]
    assert 'name="class"' in class_filter
    assert 'name="species"' in html.split('data-only="species"')[1].split("</details>")[0]
    # every class repeats this one, so it is left out as in the World list (the feat stays)
    assert not re.search(r"Ability Score Improvement</span>\s*<span[^>]*>Class", html)
    row = html.split(f'data-feature="feature:{known.pk}"')[1].split("</li>")[0]
    assert " disabled" in row.split(">")[0] and "Added" in row  # one it already has
    assert 'data-feature="feat:' in html and 'data-feature="option:' in html


def test_the_add_feature_sheet_is_for_the_owner_only(client, alice, bob):
    cleric = finished(alice, "cleric")

    assert client.get(f"/characters/{cleric.pk}/features/").status_code == 403
    client.force_login(bob)
    assert client.get(f"/characters/{cleric.pk}/features/").status_code == 403
    assert 'id="cs-add-feature"' not in client.get(f"/characters/{cleric.pk}/").content.decode()


def test_adding_and_removing_a_feature_over_http(signed_in, alice):
    from apps.rules.models import Feature

    cleric = finished(alice, "cleric")
    extra = Feature.objects.filter(class_level__klass_id="fighter").first()
    ref = f"feature:{extra.pk}"
    before = cleric.features.count()

    added = act(signed_in, cleric, action="feature_add", feature=ref)

    assert added.status_code == 200 and added.json()["refresh"] is True
    assert added.json()["message"] == f"Added {extra.name}"
    assert cleric.features.count() == before + 1
    assert act(signed_in, cleric, action="feature_add", feature=ref).status_code == 400
    assert act(signed_in, cleric, action="feature_add", feature="nope").status_code == 400
    assert act(signed_in, cleric, action="feature_add", feature="feature:0").status_code == 400

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "features")
    row = next(chunk for chunk in html.split("<li") if f"/world/feats/feature/{extra.pk}/" in chunk)
    assert f'data-feature="{ref}"' in row and 'class="item-remove"' in row
    # what the builder granted has no remove button
    granted = cleric.features.exclude(feature=extra).first().feature
    granted_row = next(
        chunk for chunk in html.split("<li") if f"/world/feats/feature/{granted.pk}/" in chunk
    )
    assert "item-remove" not in granted_row

    assert act(signed_in, cleric, action="feature_remove", feature=ref).status_code == 200
    assert cleric.features.count() == before
    assert act(signed_in, cleric, action="feature_remove", feature=ref).status_code == 400
    granted_ref = f"feature:{granted.pk}"
    assert act(signed_in, cleric, action="feature_remove", feature=granted_ref).status_code == 400


def test_adding_and_removing_a_feat_and_an_option_over_http(signed_in, alice):
    from apps.rules.models import Feat, OptionalFeature

    cleric = finished(alice, "cleric")
    feat = next(  # one without choices of its own (those ask for them first)
        f
        for f in Feat.objects.exclude(pk__in=cleric.feats.values_list("feat_id", flat=True))
        if not progression.sheet_feat_pickers(cleric, f, {})
    )
    option = OptionalFeature.objects.first()

    assert (
        act(signed_in, cleric, action="feature_add", feature=f"feat:{feat.pk}").status_code == 200
    )
    assert (
        act(signed_in, cleric, action="feature_add", feature=f"option:{option.pk}").status_code
        == 200
    )
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "features")
    assert f'data-feature="feat:{feat.pk}"' in html and f'data-feature="option:{option.pk}"' in html

    assert (
        act(signed_in, cleric, action="feature_remove", feature=f"feat:{feat.pk}").status_code
        == 200
    )
    assert (
        act(signed_in, cleric, action="feature_remove", feature=f"option:{option.pk}").status_code
        == 200
    )
    assert not cleric.optional_features.filter(optional_feature=option).exists()


def test_a_non_owner_cannot_add_or_remove_a_feature(client, alice, bob):
    cleric = finished(alice, "cleric")
    client.force_login(bob)

    assert act(client, cleric, action="feature_add", feature="feat:alert").status_code == 403


# --- clearing filters --------------------------------------------------------------------------


def test_every_search_form_with_filters_has_a_clear_filters_button(signed_in, alice):
    cleric = finished(alice, "cleric")

    for url in ("/world/spells/", "/world/feats/", f"/characters/{cleric.pk}/spells/"):
        html = signed_in.get(url).content.decode()
        assert "data-filter-clear" in html and "Clear filters" in html, url
    sheet = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert panel(sheet, "spellbook").count("data-filter-clear") == 1
    assert panel(sheet, "features").count("data-filter-clear") == 1
    assert re.search(r'<script src="/static/js/filter_clear\.js\?v=\d+"></script>', sheet)


def test_a_search_form_without_filters_has_no_clear_filters_button(signed_in):
    assert "data-filter-clear" not in signed_in.get("/world/languages/").content.decode()


def test_casting_a_prepared_spell_spends_a_slot_of_that_level_and_a_cantrip_none(signed_in, alice):
    cleric = finished(alice, "cleric")
    spell = cleric.spells.filter(spell__level=1, prepared=True).first().spell
    cantrip = cleric.spells.filter(spell__level=0).first().spell

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    assert f'data-cast="{spell.pk}"' in html and f'data-cast="{cantrip.pk}"' in html

    assert act(signed_in, cleric, action="cast", spell=cantrip.pk).status_code == 200
    cleric.refresh_from_db()
    assert cleric.spell_slots_spent == {}
    assert act(signed_in, cleric, action="cast", spell=spell.pk, slot="1").status_code == 200
    cleric.refresh_from_db()
    assert cleric.spell_slots_spent == {"1": 1}
    act(signed_in, cleric, action="cast", spell=spell.pk, slot="1")
    assert act(signed_in, cleric, action="cast", spell=spell.pk, slot="1").status_code == 400
    assert act(signed_in, cleric, action="cast", spell=spell.pk, slot="9").status_code == 400


def test_the_owner_can_delete_a_character_and_only_the_owner(client, alice, bob):
    hero = finished(alice, "cleric")
    client.force_login(bob)
    assert client.post(f"/characters/{hero.pk}/delete/").status_code == 403
    assert Character.objects.filter(pk=hero.pk).exists()
    assert f"/characters/{hero.pk}/delete/" not in client.get("/characters/").content.decode()

    client.force_login(alice)
    assert f"/characters/{hero.pk}/delete/" in client.get("/characters/").content.decode()
    assert client.post(f"/characters/{hero.pk}/delete/").status_code == 302
    assert not Character.objects.filter(pk=hero.pk).exists()


def test_an_admin_account_is_an_admin_who_can_delete_and_edit_anyones_character(client, alice):
    hero = finished(alice, "cleric")
    anna = get_user_model().objects.create_user("Scimone.Mail@gmail.com")
    client.force_login(anna)

    assert (
        client.post(f"/characters/{hero.pk}/act/", {"action": "xp", "value": "5"}).status_code
        == 200
    )
    assert client.post(f"/characters/{hero.pk}/delete/").status_code == 302
    assert not Character.objects.filter(pk=hero.pk).exists()


def test_a_character_in_creation_can_be_deleted_from_the_overview(signed_in, alice):
    draft = build_character(alice, "cleric", "acolyte", "human", "Draft")
    assert f"/characters/{draft.pk}/delete/" in signed_in.get("/characters/").content.decode()

    assert signed_in.post(f"/characters/{draft.pk}/delete/").status_code == 302
    assert not Character.objects.filter(pk=draft.pk).exists()


def test_a_cast_button_is_hidden_when_no_slot_is_left_for_the_spell(signed_in, alice):
    cleric = finished(alice, "cleric")
    spell = (
        cleric.spells.filter(spell__level=1, prepared=True, spell__ritual=False, free_cast=False)
        .first()
        .spell
    )
    tag = f'data-cast="{spell.pk}"'

    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert tag in html and "hidden" not in re.search(
        r"<button[^>]*" + re.escape(tag) + r"[^>]*>", html
    ).group(0)
    play.set_slots_spent(cleric, "1", 2, 2)
    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert "hidden" in re.search(r"<button[^>]*" + re.escape(tag) + r"[^>]*>", html).group(0)


def test_a_magic_initiate_spell_can_be_cast_once_without_a_slot(signed_in, alice):
    cleric = finished(alice, "cleric")
    row = cleric.spells.filter(spell__level=1, prepared=True, spell__ritual=False).first()
    row.free_cast = True
    row.save()
    play.set_slots_spent(cleric, "1", 2, 2)  # every slot spent
    tag = f'data-cast="{row.spell_id}"'

    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert "hidden" not in re.search(r"<button[^>]*" + re.escape(tag) + r"[^>]*>", html).group(0)
    assert act(signed_in, cleric, action="cast", spell=row.spell_id, free="1").status_code == 200
    assert act(signed_in, cleric, action="cast", spell=row.spell_id, free="1").status_code == 400
    cleric.refresh_from_db()
    assert cleric.spell_slots_spent == {"1": 2}  # no slot was used

    play.long_rest(cleric)
    assert act(signed_in, cleric, action="cast", spell=row.spell_id, free="1").status_code == 200


def test_the_rest_buttons_and_the_resources_show_and_the_actions_work(signed_in, alice):
    fighter = finished(alice, "fighter")
    fighter.current_hit_points = 3
    fighter.save()
    stats = panel(signed_in.get(f"/characters/{fighter.pk}/").content.decode(), "stats")
    assert 'data-rest="short"' in stats and 'data-rest="long"' in stats
    assert "Second Wind" in stats

    response = act(signed_in, fighter, action="short_rest", rolls="d10:6")
    assert response.status_code == 200
    fighter.refresh_from_db()
    assert fighter.current_hit_points > 3 and play.hit_dice_left(fighter) == {"d10": 0}
    assert act(signed_in, fighter, action="short_rest", rolls="d10:6").status_code == 400

    assert act(signed_in, fighter, action="long_rest").status_code == 200
    fighter.refresh_from_db()
    assert fighter.current_hit_points == fighter.max_hit_points
    wind = fighter.resources.get(name="Second Wind")
    # The counter is not the player's to set: only the feature's Use button spends it.
    assert act(signed_in, fighter, action="resource", id=wind.pk, delta="-1").status_code == 400
    html = signed_in.get(f"/characters/{fighter.pk}/").content.decode()
    assert 'data-act="resource"' not in html
    assert act(signed_in, fighter, action="resource_use", resource=wind.pk).status_code == 400
    use = f"feature:{Feature.objects.get(name_en='Second Wind').pk}"
    assert act(signed_in, fighter, action="feature_use", use=use, roll="3").status_code == 200
    assert fighter.resources.get(name="Second Wind").current_uses == wind.max_uses - 1


def test_a_thrown_or_ranged_weapon_lists_its_range_as_a_property(signed_in, alice):
    response = signed_in.get("/characters/describe/equipment/dagger/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "Range 6/18 m" in html  # 20/60 ft
    assert (
        "Range 45/180 m"
        in signed_in.get("/characters/describe/equipment/longbow/").content.decode()
    )
    assert "Range" not in signed_in.get("/characters/describe/equipment/club/").content.decode()


def test_the_overview_shows_a_picture_and_level_wording(signed_in, alice):
    finished(alice, "monk")

    html = signed_in.get("/characters/?view=list").content.decode()

    assert 'class="item-thumb pic-empty"' in html and "Monk · Level 1" in html


def test_the_purse_has_plus_buttons_and_italian_coin_abbreviations_for_others(
    signed_in, alice, bob
):
    cleric = finished(alice, "cleric")
    signed_in.cookies["django_language"] = "it"

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")

    # The owner's coins are "+" buttons (the coin's name is in the label, not the disc).
    assert html.count('data-coin-add="') == 4 and ">+</button>" in html
    assert ">GP<" not in html and ">MO<" not in html

    # Someone else's sheet is read-only and keeps the abbreviations.
    signed_in.force_login(bob)
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "inventory")
    for abbreviation in ("MR", "MA", "MO", "MP"):
        assert f'aria-hidden="true">{abbreviation}<' in html


def test_the_manifest_is_fetched_with_credentials(signed_in):
    html = signed_in.get("/characters/").content.decode()

    assert '<link rel="manifest" href="/manifest.json" crossorigin="use-credentials">' in html


def test_world_items_has_the_same_filters_as_the_add_item_sheet(signed_in, alice):
    world = signed_in.get("/world/items/").content.decode()
    cleric = finished(alice, "cleric")
    sheet = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()
    for name in ("section", "type", "category", "property", "mastery"):
        assert f'name="{name}"' in world and f'name="{name}"' in sheet

    weapons = signed_in.get("/world/items/?section=weapons").content.decode()
    armor = signed_in.get("/world/items/?section=armor").content.decode()
    assert "Longsword" in weapons and "Longsword" not in armor
    assert "Chain Mail" in armor and "Chain Mail" not in weapons
    martial = signed_in.get("/world/items/?section=weapons&category=simple").content.decode()
    assert "Longsword" not in martial and "Club" in martial


def test_adding_magic_initiate_by_hand_asks_for_its_list_and_spells(signed_in, alice):
    fighter = finished(alice, "fighter", background="soldier")
    feature = "feat:magic-initiate"

    row = signed_in.get(f"/characters/{fighter.pk}/features/").content.decode()
    assert f'data-picks-url="/characters/{fighter.pk}/feature-picks/"' in row

    first = signed_in.get(f"/characters/{fighter.pk}/feature-picks/", {"feature": feature})
    assert 'name="pick.lu.feat.variant"' in first.content.decode()
    assert "cantrips" not in first.content.decode()  # the list is chosen first
    assert act(signed_in, fighter, action="feature_add", feature=feature).status_code == 400

    variant = {"pick.lu.feat.variant": "cleric"}
    second = signed_in.get(
        f"/characters/{fighter.pk}/feature-picks/", {"feature": feature, **variant}
    )
    assert 'name="pick.lu.feat.cantrips"' in second.content.decode()
    pickers = progression.sheet_feat_pickers(
        fighter, Feat.objects.get(pk="magic-initiate"), {"lu.feat.variant": ["cleric"]}
    )
    chosen = {
        f"pick.{p.key}": ",".join([c[0] for c in p.candidates][: 1 if p.single else p.count])
        for p in pickers
        if p.key != "lu.feat.variant"
    }
    response = act(signed_in, fighter, action="feature_add", feature=feature, **variant, **chosen)

    assert response.status_code == 200
    assert fighter.feats.filter(feat_id="magic-initiate").exists()
    granted = fighter.spells.filter(source="feat:magic-initiate")
    assert granted.filter(spell__level=0).count() == 2
    assert granted.filter(spell__level=1, free_cast=True).count() == 1

    act(signed_in, fighter, action="feature_remove", feature=feature)
    assert not fighter.spells.filter(source="feat:magic-initiate").exists()


def test_hit_points_that_change_the_conditions_ask_for_a_redraw(signed_in, alice):
    cleric = finished(alice, "cleric")
    maximum = cleric.hit_point_maximum

    # a plain loss of hit points changes nothing else, so the script needn't redraw
    assert act(signed_in, cleric, action="hp_delta", delta="-1").json()["refresh"] is False

    # dropping to 0 stores Unconscious (and Prone): the Conditions card must follow at once
    down = act(signed_in, cleric, action="hp_set", value="0").json()
    assert down["refresh"] is True
    cleric.refresh_from_db()
    assert "unconscious" in cleric.conditions

    # healing ends it; crossing half the maximum flips Bloodied, which also redraws
    up = act(signed_in, cleric, action="hp_set", value=str(maximum // 2 + 1)).json()
    assert up["refresh"] is True
    cleric.refresh_from_db()
    assert "unconscious" not in cleric.conditions and "prone" in cleric.conditions
    assert (
        act(signed_in, cleric, action="hp_set", value=str(maximum // 2)).json()["refresh"] is True
    )


def test_the_slot_descriptions_are_tooltip_data_for_players(signed_in, alice):
    cleric = finished(alice, "cleric")
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    assert 'data-tip-title="Spell Slots"' in html
    assert "All slots reset after a Long Rest." in html


# --- the campaign's permanent custom catalog, and handing items to another character ----------


def test_a_custom_item_stays_in_the_campaigns_catalog_and_can_be_added_again(signed_in, alice):
    cleric = finished(alice, "cleric")
    from apps.characters.models import CharacterCustomItem, CustomCatalogItem

    act(signed_in, cleric, action="custom_add", name="Ruby", section="misc", cost="50")
    entry = CustomCatalogItem.objects.get(campaign=cleric.campaign, name="Ruby")
    assert entry.value == 5000

    act(signed_in, cleric, action="custom_add", name="ruby", section="misc", cost="60")
    assert CustomCatalogItem.objects.filter(campaign=cleric.campaign).count() == 1  # refreshed

    CharacterCustomItem.objects.filter(
        character=cleric
    ).delete()  # gone from the sheet, not the catalog
    again = act(signed_in, cleric, action="custom_catalog_add", entry=entry.pk, quantity="2")
    assert again.status_code == 200
    item = cleric.custom_items.get()
    assert (item.name, item.quantity, item.value) == ("ruby", 2, 6000)

    page = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()
    assert "data-custom-entry" in page and 'data-act="custom_catalog_add"' in page


def test_transferring_items_moves_them_to_another_character_of_the_campaign(signed_in, alice):
    from apps.characters.models import CharacterInventoryItem

    cleric = finished(alice, "cleric")
    friend = finished(alice, "cleric", name="Friend")
    play.add_custom_item(cleric, name="Locket", quantity=1)
    locket = cleric.custom_items.get()
    torches = CharacterInventoryItem.objects.create(
        character=cleric, equipment_id="torch", quantity=10
    )

    items = json.dumps(
        [
            {"kind": "custom", "item": locket.pk, "quantity": 1},
            {"kind": "catalog", "item": torches.pk, "quantity": 4},
        ]
    )
    reply = act(signed_in, cleric, action="item_transfer", to=friend.pk, items=items)

    assert reply.status_code == 200
    assert not cleric.custom_items.exists()
    torches.refresh_from_db()
    assert torches.quantity == 6
    assert friend.custom_items.get().name == "Locket"
    assert friend.inventory_items.get(equipment_id="torch").quantity == 4

    # Not to oneself, and not more than once per item.
    assert (
        act(signed_in, cleric, action="item_transfer", to=cleric.pk, items=items).status_code == 400
    )


def test_the_plus_on_a_coin_adds_money(signed_in, alice):
    cleric = finished(alice, "cleric")
    play.set_coin(cleric, "gold", 5)
    page = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert 'data-coin-add="gold"' in page and 'id="cs-coin-dialog"' in page

    assert act(signed_in, cleric, action="coin_add", coin="gold", value="15").status_code == 200
    assert cleric.currency.gold == 20
    for bad in ("0", "-3", "x"):
        assert act(signed_in, cleric, action="coin_add", coin="gold", value=bad).status_code == 400
    assert act(signed_in, cleric, action="coin_add", coin="gems", value="1").status_code == 400
    cleric.currency.refresh_from_db()
    assert cleric.currency.gold == 20


def test_money_passes_between_characters_with_or_without_items(signed_in, alice):
    cleric = finished(alice, "cleric")
    friend = finished(alice, "cleric", name="Friend")
    play.set_coin(cleric, "gold", 10)
    play.set_coin(cleric, "silver", 3)
    coins = json.dumps({"gold": 4, "silver": 3})
    friend_gold = getattr(getattr(friend, "currency", None), "gold", 0)
    friend_silver = getattr(getattr(friend, "currency", None), "silver", 0)

    reply = act(signed_in, cleric, action="item_transfer", to=friend.pk, items="[]", coins=coins)
    assert reply.status_code == 200
    cleric.currency.refresh_from_db()
    assert (cleric.currency.gold, cleric.currency.silver) == (6, 0)
    friend.currency.refresh_from_db()
    assert (friend.currency.gold, friend.currency.silver) == (friend_gold + 4, friend_silver + 3)

    # Never more than the purse holds, and nothing moves when any amount is wrong.
    too_much = json.dumps({"silver": 1, "gold": 7})
    reply = act(signed_in, cleric, action="item_transfer", to=friend.pk, items="[]", coins=too_much)
    assert reply.status_code == 400
    cleric.currency.refresh_from_db()
    friend.currency.refresh_from_db()
    assert (cleric.currency.gold, friend.currency.gold) == (6, friend_gold + 4)
    assert (
        act(signed_in, cleric, action="item_transfer", to=friend.pk, items="[]").status_code == 400
    )


def _unknown_spells(character, count=2):
    return list(
        Spell.objects.exclude(pk__in=character.spells.values_list("spell_id", flat=True)).filter(
            level__gt=0
        )[:count]
    )


def test_a_custom_feature_grants_always_prepared_spells(signed_in, alice):
    cleric = finished(alice, "cleric")
    first, second = _unknown_spells(cleric)
    reply = act(
        signed_in,
        cleric,
        action="custom_feature_add",
        name="Fey Gift",
        spells=json.dumps([first.pk, second.pk]),
    )
    assert reply.status_code == 200
    rows = cleric.spells.filter(source__startswith="custom:")
    assert {r.spell_id for r in rows} == {first.pk, second.pk}
    assert all(r.prepared and r.always_prepared for r in rows)

    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    assert "Always prepared (Fey Gift)" in html and f"/world/spells/{first.pk}/" in html
    # They are not the player's to remove or unprepare.
    row = next(c for c in html.split("<li") if f"/world/spells/{first.pk}/" in c)
    assert "spell_remove" not in row and "spell_prepare" not in row

    # Dropping one spell from the feature, then the feature itself, takes the spells away.
    feature = cleric.custom_features.get()
    act(signed_in, cleric, action="custom_feature_edit", feature=feature.pk, name="Fey Gift",
        spells=json.dumps([second.pk]))  # fmt: skip
    assert set(
        cleric.spells.filter(source__startswith="custom:").values_list("spell_id", flat=True)
    ) == {second.pk}
    act(signed_in, cleric, action="custom_feature_remove", feature=feature.pk)
    assert not cleric.spells.filter(source__startswith="custom:").exists()

    bad = act(signed_in, cleric, action="custom_feature_add", name="Bad", spells='["nope"]')
    assert bad.status_code == 400


def test_a_custom_item_grants_spells_only_while_equipped(signed_in, alice):
    cleric = finished(alice, "cleric")
    (spell,) = _unknown_spells(cleric, 1)
    act(
        signed_in,
        cleric,
        action="custom_add",
        name="Staff of Sparks",
        section="misc",
        spells=json.dumps([spell.pk]),
    )
    item = cleric.custom_items.get()
    assert item.spells == [{"id": spell.pk, "free": ""}]
    assert not cleric.spells.filter(spell=spell).exists()  # carried, not worn

    act(signed_in, cleric, action="equip", kind="custom", item=item.pk, value="1")
    row = cleric.spells.get(spell=spell)
    assert row.always_prepared and row.source == f"custom:item:{item.pk}"

    act(signed_in, cleric, action="equip", kind="custom", item=item.pk, value="0")
    assert not cleric.spells.filter(spell=spell).exists()

    # Worn again, then gone from the sheet altogether: the spell goes too.
    act(signed_in, cleric, action="equip", kind="custom", item=item.pk, value="1")
    act(signed_in, cleric, action="item_remove", kind="custom", item=item.pk)
    assert not cleric.spells.filter(spell=spell).exists()


def test_a_spell_the_character_already_has_is_not_doubled_or_removed(signed_in, alice):
    cleric = finished(alice, "cleric")
    (spell,) = _unknown_spells(cleric, 1)
    act(signed_in, cleric, action="spell_add", spell=spell.pk)
    act(signed_in, cleric, action="custom_feature_add", name="Echo", spells=json.dumps([spell.pk]))
    assert cleric.spells.filter(spell=spell).count() == 1
    act(signed_in, cleric, action="custom_feature_remove", feature=cleric.custom_features.get().pk)
    assert cleric.spells.filter(spell=spell).exists()  # the player's own stays


def test_wild_shape_forms_are_feature_cards_with_stat_blocks_and_a_swap_after_a_rest(
    signed_in, alice
):
    from apps.builder.services import wild_shape

    druid = finished(alice, "druid", name="Moss")
    druid.classes.update(level=2)
    html = panel(signed_in.get(f"/characters/{druid.pk}/").content.decode(), "features")
    assert "Wild Shape: Wolf" not in html and "data-wild-open" in html  # none learnt yet
    assert 'data-mode="learn"' in html and 'data-count="4"' in html

    forms = "wolf,rat,spider,riding-horse"
    assert act(signed_in, druid, action="wild_shape_choose", forms=forms).status_code == 200
    html = panel(signed_in.get(f"/characters/{druid.pk}/").content.decode(), "features")
    assert "Wild Shape: Wolf" in html and "/world/creatures/wolf/" in html
    assert "data-wild-open" not in html  # nothing to choose or replace right now

    page = signed_in.get("/world/creatures/wolf/").content.decode()
    assert "Pack Tactics" in page and "Armor Class" in page and "DEX" in page
    described = signed_in.get("/characters/describe/creature/wolf/").content.decode()
    assert "Pack Tactics" in described

    act(signed_in, druid, action="long_rest")
    html = panel(signed_in.get(f"/characters/{druid.pk}/").content.decode(), "features")
    assert 'data-mode="swap"' in html and 'name="ws_old"' in html
    reply = act(signed_in, druid, action="wild_shape_swap", old="wolf", new="boar")
    assert reply.status_code == 200
    assert "boar" in wild_shape.known_ids(druid) and "wolf" not in wild_shape.known_ids(druid)
    assert act(signed_in, druid, action="wild_shape_swap", old="rat", new="cat").status_code == 400


def test_a_granted_spell_can_be_cast_free_once_per_rest_or_without_limit(signed_in, alice):
    cleric = finished(alice, "cleric")
    long_, short_, unlimited, plain = _unknown_spells(cleric, 4)
    entries = [
        {"id": long_.pk, "free": "long"},
        {"id": short_.pk, "free": "short"},
        {"id": unlimited.pk, "free": "unlimited"},
        {"id": plain.pk, "free": ""},
    ]
    act(signed_in, cleric, action="custom_feature_add", name="Boon", spells=json.dumps(entries))
    rows = {r.spell_id: r for r in cleric.spells.filter(source__startswith="custom:")}
    assert (rows[long_.pk].free_cast, rows[long_.pk].free_cast_recharge) == (True, "long")
    assert (rows[short_.pk].free_cast, rows[short_.pk].free_cast_recharge) == (True, "short")
    assert rows[unlimited.pk].free_cast_unlimited and not rows[unlimited.pk].free_cast
    assert not (rows[plain.pk].free_cast or rows[plain.pk].free_cast_unlimited)

    # Spend the two free casts: a short rest restores only the one that says so.
    cleric.spells.filter(spell_id__in=[long_.pk, short_.pk]).update(free_cast_used=True)
    play.short_rest(cleric, [], 0)
    assert cleric.spells.get(spell_id=short_.pk).free_cast_used is False
    assert cleric.spells.get(spell_id=long_.pk).free_cast_used is True
    play.long_rest(cleric)
    assert cleric.spells.get(spell_id=long_.pk).free_cast_used is False

    # Editing the grant changes the flags; a bad value is refused.
    feature = cleric.custom_features.get()
    changed = json.dumps([{"id": long_.pk, "free": ""}])
    act(
        signed_in,
        cleric,
        action="custom_feature_edit",
        feature=feature.pk,
        name="Boon",
        spells=changed,
    )
    row = cleric.spells.get(spell_id=long_.pk)
    assert not row.free_cast and not cleric.spells.filter(spell_id=short_.pk).exists()
    bad = json.dumps([{"id": long_.pk, "free": "daily"}])
    assert (
        act(signed_in, cleric, action="custom_feature_add", name="X", spells=bad).status_code == 400
    )


def test_the_spell_picker_lists_spells_with_search_filters_and_a_free_cast_choice(signed_in, alice):
    cleric = finished(alice, "cleric")
    html = signed_in.get("/spells/picker/").content.decode()
    assert "data-spk-search" in html and 'data-spk-filter="level"' in html
    assert 'data-spk-filter="school"' in html and "data-spk-free" in html
    assert html.count("data-spk-add") >= Spell.objects.count()
    assert "/characters/describe/spell/" in html
    signed_in.logout()
    assert signed_in.get("/spells/picker/").status_code == 403

    # The editor on the forms carries the picker's address and the chosen spells.
    signed_in.force_login(alice)
    page = signed_in.get(f"/characters/{cleric.pk}/items/").content.decode()
    assert "data-spells-open" in page and 'data-picker-url="/spells/picker/"' in page


def test_using_wild_shape_swaps_in_the_beasts_statistics_until_it_ends(signed_in, alice):
    from apps.builder.services import derived_stats, wild_shape
    from apps.characters.models import CharacterResource
    from apps.rules.models import Creature

    druid = finished(alice, "druid", name="Moss")
    druid.classes.update(level=4)
    wild_shape.add_forms(druid, ["wolf", "rat", "spider", "riding-horse", "boar", "cat"])
    CharacterResource.objects.create(
        character=druid, name="Wild Shape", max_uses=2, current_uses=2, reset_on="other"
    )
    own = derived_stats.compute(druid)
    page = panel(signed_in.get(f"/characters/{druid.pk}/").content.decode(), "features")
    assert 'data-act="wild_shape_use"' in page and 'data-form="wolf"' in page

    assert act(signed_in, druid, action="wild_shape_use", form="wolf").status_code == 200
    druid.refresh_from_db()
    wolf = Creature.objects.get(pk="wolf")
    stats = derived_stats.compute(druid)
    assert druid.wild_shape_form == "wolf" and druid.temporary_hit_points == 4
    assert druid.resources.get(name="Wild Shape").current_uses == 1
    assert stats.armor_class["value"] == wolf.ac and stats.speed == 40
    assert stats.abilities["str"]["score"] == 14 and stats.abilities["dex"]["score"] == 15
    assert stats.abilities["wis"] == own.abilities["wis"]  # the mind stays
    assert stats.skills["stealth"]["modifier"] >= 4  # the stat block's bonus, if higher
    html = signed_in.get(f"/characters/{druid.pk}/").content.decode()
    assert (
        '<details class="cs-shaped"' in html
        and 'data-act="wild_shape_end"' in html
        and "Pack Tactics" in html
    )

    # No spells while shaped; using it again changes form and spends another use.
    spell = druid.spells.filter(spell__level=0).first() or druid.spells.first()
    if spell:
        reply = act(signed_in, druid, action="cast", spell=spell.spell_id, slot="")
        assert reply.status_code == 400
    assert act(signed_in, druid, action="wild_shape_use", form="boar").status_code == 200
    assert act(signed_in, druid, action="wild_shape_use", form="cat").status_code == 400  # no uses
    druid.refresh_from_db()
    assert druid.wild_shape_form == "boar"

    assert act(signed_in, druid, action="wild_shape_end").status_code == 200
    druid.refresh_from_db()
    assert (
        druid.wild_shape_form == ""
        and '<details class="cs-shaped"'
        not in signed_in.get(f"/characters/{druid.pk}/").content.decode()
    )
    assert derived_stats.compute(druid).armor_class == own.armor_class


def test_wild_shape_ends_at_zero_hit_points_and_on_a_long_rest(signed_in, alice):
    from apps.builder.services import wild_shape
    from apps.characters.models import CharacterResource

    druid = finished(alice, "druid", name="Moss")
    druid.classes.update(level=2)
    wild_shape.add_forms(druid, ["wolf", "rat", "spider", "riding-horse"])
    CharacterResource.objects.create(
        character=druid, name="Wild Shape", max_uses=2, current_uses=2, reset_on="other"
    )
    act(signed_in, druid, action="wild_shape_use", form="wolf")
    act(signed_in, druid, action="hp_set", value="0")
    druid.refresh_from_db()
    assert druid.wild_shape_form == ""  # Unconscious means Incapacitated

    act(signed_in, druid, action="hp_set", value="3")
    act(signed_in, druid, action="wild_shape_use", form="rat")
    act(signed_in, druid, action="long_rest")
    druid.refresh_from_db()
    assert druid.wild_shape_form == ""
    assert druid.resources.get(name="Wild Shape").current_uses == 2


def test_a_free_cast_says_which_rest_gives_it_back(signed_in, alice):
    cleric = finished(alice, "cleric")
    (spell,) = _unknown_spells(cleric, 1)
    entries = json.dumps([{"id": spell.pk, "free": "short"}])
    act(signed_in, cleric, action="custom_feature_add", name="Boon", spells=entries)
    html = panel(signed_in.get(f"/characters/{cleric.pk}/").content.decode(), "spellbook")
    assert 'data-cast-free-kind="short"' in html
    page = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert "once per short rest" in page and "data-cast-free-label" in page
