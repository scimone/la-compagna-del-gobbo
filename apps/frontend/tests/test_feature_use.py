"""The Use button of every feature that has (or spends) a counter, and the features split into
one card per option."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.builder.progression_spec import LEVEL_RESOURCES
from apps.builder.services import creation, wild_shape
from apps.builder.services.feature_resources import FEATURE_RESOURCES
from apps.builder.tests.conftest import build_character
from apps.characters.models import CharacterFeature, CharacterResource
from apps.characters.services import feature_use
from apps.rules.models import Feature, OptionalFeature

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def signed_in(client, alice):
    client.force_login(alice)
    return client


def finished(owner, class_id, background="acolyte", species="human"):
    character = build_character(owner, class_id, background, species, "Test")
    creation.finalize(character)
    character.refresh_from_db()
    return character


def act(client, character, **data):
    return client.post(f"/characters/{character.pk}/act/", data)


def features_panel(client, character):
    html = client.get(f"/characters/{character.pk}/").content.decode()
    return html.split('data-panel="features"')[1].split('data-panel="spellbook"')[0]


def give(character, name, owner=None, **resource):
    """The feature (of `owner`: a class id or subclass name) and the counters on the sheet."""
    features = Feature.objects.filter(name_en=name)
    if owner:
        features = features.filter(
            Q(class_level__klass_id=owner) | Q(subclass_level__subclass__name_en=owner)
        )
    feature = features.first()
    CharacterFeature.objects.get_or_create(character=character, feature=feature)
    for res, (current, maximum) in resource.items():
        CharacterResource.objects.update_or_create(
            character=character,
            name=res.replace("_", " "),
            defaults={"max_uses": maximum, "current_uses": current, "reset_on": "long_rest"},
        )


def plain(entries) -> str:
    if isinstance(entries, str):
        return entries
    if isinstance(entries, list):
        return " ".join(plain(e) for e in entries)
    if isinstance(entries, dict):
        return (
            (entries.get("name") or "")
            + " "
            + plain(entries.get("entries") or entries.get("items") or "")
        )
    return ""


def test_every_counter_can_be_spent_from_some_card(db):
    own = {r.name for rows in LEVEL_RESOURCES.values() for r in rows}
    own |= {r.feature for r in FEATURE_RESOURCES}
    spent = {u.resource for u in feature_use.SPENDS.values() if u.resource}
    spent |= {u.resource for u in feature_use.EFFECTS.values() if u.resource}
    spent |= {
        u.resource for parts in feature_use.PARTS.values() for _n, u in parts if u and u.resource
    }
    cards = {n.split(" (")[0] for n in Feature.objects.values_list("name_en", flat=True)}
    aliases = {
        "Focus Points",
        "Sorcery Points",
        "Superiority Dice",
        "Channel Divinity",
        "Wild Shape",
    }
    unreachable = [
        n
        for n in sorted(own)
        if n not in spent and n not in feature_use.NO_BUTTON and n not in aliases and n not in cards
    ]
    assert unreachable == []
    # The pools of points are spent by the cards of the features that use them.
    assert {"Focus Points", "Sorcery Points", "Superiority Dice", "Channel Divinity"} <= spent | {
        u.resource for u in (feature_use.option_use("Maneuver, Battle Master", ""),)
    }


def test_the_use_tables_name_real_features_and_real_options(db):
    names = {n.split(" (")[0] for n in Feature.objects.values_list("name_en", flat=True)}
    missing = [n for n in (*feature_use.SPENDS, *feature_use.EFFECTS) if n not in names]
    assert missing == []
    for (parent, _owner), parts in feature_use.PARTS.items():
        assert parent in names, parent
        text = " ".join(
            plain(f.entries) for f in Feature.objects.filter(name_en__startswith=parent)
        )
        for part, _spec in parts:
            if parent not in ("Wild Resurgence",):  # its options are not named in its text
                assert part.lower() in text.lower(), (parent, part)


def test_a_feature_with_a_counter_has_a_use_button_without_numbers(signed_in, alice):
    fighter = finished(alice, "fighter", "soldier")
    wind = fighter.resources.get(name="Second Wind")
    wind.current_uses = wind.max_uses
    wind.save()
    panel = features_panel(signed_in, fighter)
    row = next(c for c in panel.split("<li") if "Second Wind" in c)
    assert 'data-act="feature_use"' in row and ">Use</button>" in row and "Use 2" not in row
    assert "Roll 1d10" in row  # Second Wind asks for the roll it heals with

    use = {"use": f"feature:{Feature.objects.get(name_en='Second Wind').pk}", "roll": "3"}
    assert act(signed_in, fighter, action="feature_use", **use).status_code == 200
    assert act(signed_in, fighter, action="feature_use", **use).status_code == 200
    assert act(signed_in, fighter, action="feature_use", **use).status_code == 400
    row = next(c for c in features_panel(signed_in, fighter).split("<li") if "Second Wind" in c)
    assert "feature_use" not in row  # none left: no button
    act(signed_in, fighter, action="long_rest")
    assert "feature_use" in features_panel(signed_in, fighter)


def test_monks_focus_is_split_into_one_card_per_option(signed_in, alice):
    monk = finished(alice, "monk")
    give(monk, "Monk's Focus", Focus_Points=(2, 2))
    panel = features_panel(signed_in, monk)
    cards = {m.group(1) for m in re.finditer(r"Monk&#x27;s Focus: ([A-Za-z ]+)", panel)}
    assert cards == {"Flurry of Blows", "Patient Defense", "Step of the Wind"}
    focus = next(c for c in panel.split("<li") if re.search(r"item-name\">Monk&#x27;s Focus<", c))
    assert "feature_use" not in focus  # the feature itself has no button
    flurry = next(c for c in panel.split("<li") if "Monk&#x27;s Focus: Flurry" in c)
    assert 'data-part="flurry-of-blows"' in flurry and "feature_use" in flurry

    feature = Feature.objects.get(name_en="Monk's Focus")
    reply = act(
        signed_in, monk, action="feature_use", use=f"feature:{feature.pk}", part="flurry-of-blows"
    )
    assert reply.status_code == 200
    assert monk.resources.get(name="Focus Points").current_uses == 1
    # The option's own page shows its text.
    page = signed_in.get(f"/world/feats/feature/{feature.pk}/flurry-of-blows/").content.decode()
    assert "two Unarmed Strikes" in page and "Flurry of Blows" in page
    assert signed_in.get(f"/world/feats/feature/{feature.pk}/nonsense/").status_code == 404
    # Without a point left, no option can be used.
    patient = {"action": "feature_use", "use": f"feature:{feature.pk}", "part": "patient-defense"}
    assert act(signed_in, monk, **patient).status_code == 400  # two ways: it has to say which
    act(signed_in, monk, **patient, way="fp")
    # Without a point left the Flurry cannot be used, though the free ways still can.
    html = features_panel(signed_in, monk)
    flurry = next(c for c in html.split("<li") if "Monk&#x27;s Focus: Flurry" in c)
    assert "feature_use" not in flurry
    assert "feature_use" in next(c for c in html.split("<li") if "Patient Defense" in c)


def test_a_cleric_channel_divinity_has_its_two_effects_as_cards(signed_in, alice):
    cleric = finished(alice, "cleric")
    give(cleric, "Channel Divinity", "cleric", Channel_Divinity=(2, 2))
    panel = features_panel(signed_in, cleric)
    assert "Channel Divinity: Divine Spark" in panel and "Channel Divinity: Turn Undead" in panel
    feature = Feature.objects.get(name_en="Channel Divinity", class_level__klass_id="cleric")
    assert (
        act(signed_in, cleric, action="feature_use", use=f"feature:{feature.pk}").status_code == 400
    )
    ok = act(
        signed_in, cleric, action="feature_use", use=f"feature:{feature.pk}", part="turn-undead"
    )
    assert ok.status_code == 200 and cleric.resources.get(name="Channel Divinity").current_uses == 1


def test_features_that_spend_another_counter_have_a_use_button(signed_in, alice):
    monk = finished(alice, "monk")
    give(monk, "Stunning Strike", Focus_Points=(3, 3))
    feature = Feature.objects.get(name_en="Stunning Strike")
    assert (
        act(signed_in, monk, action="feature_use", use=f"feature:{feature.pk}").status_code == 200
    )
    assert monk.resources.get(name="Focus Points").current_uses == 2

    battle_master = OptionalFeature.objects.get(pk="parry")
    fighter = finished(alice, "fighter", "soldier")
    CharacterResource.objects.create(
        character=fighter,
        name="Superiority Dice",
        max_uses=4,
        current_uses=4,
        reset_on="short_rest",
    )
    fighter.optional_features.create(optional_feature=battle_master)
    reply = act(signed_in, fighter, action="feature_use", use="option:parry")
    assert reply.status_code == 200
    assert fighter.resources.get(name="Superiority Dice").current_uses == 3


def test_a_pool_asks_how_many_points_to_spend(signed_in, alice):
    paladin = finished(alice, "paladin", "soldier")
    pool = paladin.resources.get(name="Lay on Hands")
    feature = Feature.objects.get(name_en="Lay on Hands")
    html = features_panel(signed_in, paladin)
    assert 'data-ask="' in html and "&quot;param&quot;: &quot;amount&quot;" in html
    use = f"feature:{feature.pk}"
    assert act(signed_in, paladin, action="feature_use", use=use, amount="3").status_code == 200
    assert paladin.resources.get(name="Lay on Hands").current_uses == pool.max_uses - 3
    assert act(signed_in, paladin, action="feature_use", use=use, amount="99").status_code == 400


def test_font_of_magic_converts_slots_and_creates_them_until_the_next_long_rest(signed_in, alice):
    sorcerer = finished(alice, "sorcerer")
    sorcerer.classes.update(level=5)
    give(sorcerer, "Font of Magic", Sorcery_Points=(1, 5))
    feature = Feature.objects.get(name_en="Font of Magic")
    base = {"action": "feature_use", "use": f"feature:{feature.pk}"}

    page = features_panel(signed_in, sorcerer)
    assert "Font of Magic: Converting Spell Slots to Sorcery Points" in page
    assert "Font of Magic: Creating Spell Slots" in page

    reply = act(
        signed_in, sorcerer, **base, part="converting-spell-slots-to-sorcery-points", slot="1"
    )
    assert reply.status_code == 200
    assert sorcerer.resources.get(name="Sorcery Points").current_uses == 2  # +1 for a level 1 slot
    sorcerer.refresh_from_db()
    assert sorcerer.spell_slots_spent == {"1": 1}

    sorcerer.resources.filter(name="Sorcery Points").update(current_uses=5)
    reply = act(signed_in, sorcerer, **base, part="creating-spell-slots", slot="3")
    assert reply.status_code == 200
    sorcerer.refresh_from_db()
    assert sorcerer.created_slots == {"3": 1}
    assert (
        sorcerer.resources.get(name="Sorcery Points").current_uses == 0
    )  # a 3rd-level slot costs 5
    assert (
        act(signed_in, sorcerer, **base, part="creating-spell-slots", slot="3").status_code == 400
    )
    assert "Level 3" in signed_in.get(f"/characters/{sorcerer.pk}/").content.decode()
    act(signed_in, sorcerer, action="long_rest")
    sorcerer.refresh_from_db()
    assert sorcerer.created_slots == {}


def test_sorcerous_restoration_and_the_other_restorers(signed_in, alice):
    sorcerer = finished(alice, "sorcerer")
    sorcerer.classes.update(level=6)
    give(sorcerer, "Sorcerous Restoration", Sorcerous_Restoration=(1, 1), Sorcery_Points=(0, 6))
    feature = Feature.objects.get(name_en="Sorcerous Restoration")
    assert (
        act(signed_in, sorcerer, action="feature_use", use=f"feature:{feature.pk}").status_code
        == 200
    )
    assert sorcerer.resources.get(name="Sorcery Points").current_uses == 3  # half of level 6
    assert sorcerer.resources.get(name="Sorcerous Restoration").current_uses == 0

    barbarian = finished(alice, "barbarian")
    give(barbarian, "Persistent Rage", Persistent_Rage=(1, 1), Rage=(0, 4))
    feature = Feature.objects.get(name_en="Persistent Rage")
    act(signed_in, barbarian, action="feature_use", use=f"feature:{feature.pk}")
    assert barbarian.resources.get(name="Rage").current_uses == 4

    monk = finished(alice, "monk")
    monk.classes.update(level=15)
    give(monk, "Perfect Focus", Focus_Points=(1, 15))
    feature = Feature.objects.get(name_en="Perfect Focus")
    act(signed_in, monk, action="feature_use", use=f"feature:{feature.pk}")
    assert monk.resources.get(name="Focus Points").current_uses == 4
    assert "feature_use" not in features_panel(signed_in, monk).split("Perfect Focus")[1][:700]


def test_psionic_options_free_first_use_and_wild_resurgence(signed_in, alice):
    rogue = finished(alice, "rogue")
    rogue.classes.update(level=3)
    from apps.rules.models import Subclass

    rogue.classes.update(subclass=Subclass.objects.get(name_en="Soulknife"))
    give(rogue, "Psionic Power", "Soulknife", Psionic_Power=(4, 4))
    feature = Feature.objects.get(
        name_en="Psionic Power", subclass_level__subclass__name_en="Soulknife"
    )
    base = {"action": "feature_use", "use": f"feature:{feature.pk}", "part": "psychic-whispers"}
    act(signed_in, rogue, **base)
    assert rogue.resources.get(name="Psionic Power").current_uses == 4  # the first one is free
    act(signed_in, rogue, **base)
    assert rogue.resources.get(name="Psionic Power").current_uses == 3
    act(signed_in, rogue, action="long_rest")
    rogue.refresh_from_db()
    assert rogue.use_flags == {}

    druid = finished(alice, "druid")
    druid.classes.update(level=5)
    give(druid, "Wild Resurgence", Wild_Resurgence=(1, 1), Wild_Shape=(0, 2))
    feature = Feature.objects.get(name_en="Wild Resurgence")
    base = {"action": "feature_use", "use": f"feature:{feature.pk}"}
    reply = act(signed_in, druid, **base, part="wild-shape-from-a-spell-slot", slot="1")
    assert reply.status_code == 200 and druid.resources.get(name="Wild Shape").current_uses == 1
    reply = act(signed_in, druid, **base, part="spell-slot-from-wild-shape")
    assert reply.status_code == 200
    druid.refresh_from_db()
    assert (
        druid.created_slots == {"1": 1} and druid.resources.get(name="Wild Shape").current_uses == 0
    )


def test_wild_shape_forms_and_the_counter_cards(signed_in, alice):
    druid = finished(alice, "druid")
    druid.classes.update(level=2)
    wild_shape.add_forms(druid, ["wolf", "rat", "spider", "riding-horse"])
    row = CharacterResource.objects.create(
        character=druid, name="Wild Shape", max_uses=2, current_uses=2, reset_on="other"
    )
    html = features_panel(signed_in, druid)
    assert 'data-form="wolf"' in html and ">Use</button>" in html
    assert "(2 of 2 left)" in html
    assert act(signed_in, druid, action="feature_use", use="feature:1").status_code in (400, 404)

    act(signed_in, druid, action="wild_shape_use", form="wolf")
    html = features_panel(signed_in, druid)
    assert 'data-form="wolf"' not in html and 'data-form="rat"' in html
    act(signed_in, druid, action="wild_shape_use", form="rat")
    assert 'data-form="spider"' not in features_panel(signed_in, druid)  # none left
    row.refresh_from_db()
    assert row.current_uses == 0

    other = get_user_model().objects.create_user("bob")
    signed_in.force_login(other)
    assert 'data-act="wild_shape_use"' not in features_panel(signed_in, druid)


def test_a_split_features_text_is_replaced_by_links_to_its_options(signed_in, alice):
    feature = Feature.objects.get(name_en="Monk's Focus")
    page = signed_in.get(f"/world/feats/feature/{feature.pk}/").content.decode()
    for part in ("flurry-of-blows", "patient-defense", "step-of-the-wind"):
        assert f"/world/feats/feature/{feature.pk}/{part}/" in page
    assert "Take the Disengage action" not in page and "Dash action as a Bonus Action" not in page
    assert "You start knowing three such features" in page  # the introduction stays
    cleric = Feature.objects.get(name_en="Channel Divinity", class_level__klass_id="cleric")
    text = signed_in.get(f"/world/feats/feature/{cleric.pk}/").content.decode()
    assert "/divine-spark/" in text and "Roll 1d8 and add your Wisdom modifier" not in text


def test_step_of_the_wind_and_patient_defense_offer_a_free_and_a_paid_way(signed_in, alice):
    monk = finished(alice, "monk")
    give(monk, "Monk's Focus", Focus_Points=(1, 2))
    feature = Feature.objects.get(name_en="Monk's Focus")
    html = features_panel(signed_in, monk)
    step = next(c for c in html.split("<li") if "Monk&#x27;s Focus: Step of the Wind" in c)
    assert "data-ask=" in step and "&quot;style&quot;: &quot;radio&quot;" in step
    assert (
        "Dash action as a Bonus Action - no cost" in step
        and "Focus Points \\u00d71 (1 of 2 left)" in step
    )

    base = {"action": "feature_use", "use": f"feature:{feature.pk}", "part": "step-of-the-wind"}
    assert act(signed_in, monk, **base, way="free").status_code == 200  # Dash, no Focus Point
    assert monk.resources.get(name="Focus Points").current_uses == 1
    assert act(signed_in, monk, **base, way="fp").status_code == 200
    assert monk.resources.get(name="Focus Points").current_uses == 0
    # With no point left only the free way remains.
    html = features_panel(signed_in, monk)
    step = next(c for c in html.split("<li") if "Monk&#x27;s Focus: Step of the Wind" in c)
    assert "feature_use" in step and "disengage and dash" not in step.lower()
    assert act(signed_in, monk, **base, way="fp").status_code == 400
    flurry = next(c for c in html.split("<li") if "Monk&#x27;s Focus: Flurry of Blows" in c)
    assert "feature_use" not in flurry  # no free way for the Flurry


def test_heightened_focus_renames_the_options_and_adds_its_text(signed_in, alice):
    monk = finished(alice, "monk")
    monk.classes.update(level=10)
    give(monk, "Monk's Focus", Focus_Points=(10, 10))
    give(monk, "Heightened Focus")
    focus = Feature.objects.get(name_en="Monk's Focus")
    heightened = Feature.objects.get(name_en="Heightened Focus")
    html = features_panel(signed_in, monk)
    assert "Heightened Focus: Flurry of Blows" in html and "Monk&#x27;s Focus: Flurry" not in html
    assert f"/world/feats/feature/{focus.pk}/flurry-of-blows/?with={heightened.pk}" in html

    page = signed_in.get(
        f"/world/feats/feature/{focus.pk}/flurry-of-blows/?with={heightened.pk}"
    ).content.decode()
    assert "two Unarmed Strikes" in page  # the original text ...
    assert "three Unarmed Strikes" in page  # ... and the upgrade's under it
    assert page.index("two Unarmed Strikes") < page.index("three Unarmed Strikes")
    assert "Heightened Focus: Flurry of Blows" in page
    # The plain page is not upgraded, and Heightened Focus itself links to the upgraded options.
    plain = signed_in.get(f"/world/feats/feature/{focus.pk}/flurry-of-blows/").content.decode()
    assert "three Unarmed Strikes" not in plain
    own = signed_in.get(f"/world/feats/feature/{heightened.pk}/").content.decode()
    assert f"/flurry-of-blows/?with={heightened.pk}" in own and "three Unarmed Strikes" not in own


def test_restoring_a_use_by_paying_its_price(signed_in, alice):
    paladin = finished(alice, "paladin", "soldier")
    paladin.classes.update(level=9)
    give(paladin, "Holy Nimbus", Holy_Nimbus=(0, 1))
    feature = Feature.objects.get(name_en="Holy Nimbus")
    use = {"action": "feature_use", "use": f"feature:{feature.pk}"}
    assert act(signed_in, paladin, **use).status_code == 400  # no use, and no level 5 slot to pay
    paladin.created_slots = {"5": 1}
    paladin.save()
    html = features_panel(signed_in, paladin)
    assert "a level 5 spell slot" in html
    assert act(signed_in, paladin, **use, way="restore0:5").status_code == 200
    paladin.refresh_from_db()
    assert paladin.spell_slots_spent == {"5": 1}
    assert (
        paladin.resources.get(name="Holy Nimbus").current_uses == 0
    )  # the use itself was restored


def test_restoring_with_resources_and_the_psi_warriors_new_counters(signed_in, alice):
    barbarian = finished(alice, "barbarian")
    give(
        barbarian,
        "Intimidating Presence",
        "Path of the Berserker",
        Intimidating_Presence=(0, 1),
        Rage=(3, 4),
    )
    feature = Feature.objects.get(name_en="Intimidating Presence")
    assert (
        act(
            signed_in, barbarian, action="feature_use", use=f"feature:{feature.pk}", way="restore0"
        ).status_code
        == 200
    )
    assert barbarian.resources.get(name="Rage").current_uses == 2

    from apps.builder.services import feature_resources

    fighter = finished(alice, "fighter", "soldier")
    from apps.rules.models import Subclass

    fighter.classes.update(level=3, subclass=Subclass.objects.get(name_en="Psi Warrior"))
    for name in ("Bulwark of Force", "Telekinetic Master", "Telekinetic Adept"):
        give(fighter, name, "Psi Warrior")
    feature_resources.refresh(fighter)
    names = set(fighter.resources.values_list("name", flat=True))
    assert {"Bulwark of Force", "Telekinetic Master", "Psi-Powered Leap"} <= names
    html = features_panel(signed_in, fighter)
    assert (
        "Telekinetic Adept: Psi-Powered Leap" in html
        and "Telekinetic Adept: Telekinetic Thrust" in html
    )


def test_relentless_lets_a_maneuver_skip_the_die(signed_in, alice):
    fighter = finished(alice, "fighter", "soldier")
    CharacterResource.objects.create(
        character=fighter,
        name="Superiority Dice",
        max_uses=4,
        current_uses=4,
        reset_on="short_rest",
    )
    fighter.optional_features.create(optional_feature=OptionalFeature.objects.get(pk="parry"))
    html = features_panel(signed_in, fighter)
    row = next(c for c in html.split("<li") if "Parry" in c)
    assert "data-ask=" not in row  # one way only: just the confirmation

    give(fighter, "Relentless")
    row = next(c for c in features_panel(signed_in, fighter).split("<li") if "Parry" in c)
    assert "&quot;style&quot;: &quot;radio&quot;" in row and "1d8" in row
    reply = act(signed_in, fighter, action="feature_use", use="option:parry", way="relentless")
    assert reply.status_code == 200
    assert fighter.resources.get(name="Superiority Dice").current_uses == 4  # no die spent
    act(signed_in, fighter, action="feature_use", use="option:parry", way="die")
    assert fighter.resources.get(name="Superiority Dice").current_uses == 3


def test_hit_point_features_heal(signed_in, alice):
    orc = finished(alice, "barbarian", species="orc")
    give(orc, "Relentless Endurance", Relentless_Endurance=(1, 1))
    feature = Feature.objects.get(name_en="Relentless Endurance")
    use = {"action": "feature_use", "use": f"feature:{feature.pk}"}
    orc.current_hit_points = 5
    orc.save()
    act(signed_in, orc, **use)  # not at 0 Hit Points: nothing happens
    orc.refresh_from_db()
    assert orc.current_hit_points == 5
    assert orc.resources.get(name="Relentless Endurance").current_uses == 1
    orc.current_hit_points = 0
    orc.save()
    act(signed_in, orc, **use)
    orc.refresh_from_db()
    assert orc.current_hit_points == 1
    assert orc.resources.get(name="Relentless Endurance").current_uses == 0

    fighter = finished(alice, "fighter")
    give(fighter, "Second Wind", Second_Wind=(2, 2))
    feature = Feature.objects.get(name_en="Second Wind", class_level__klass_id="fighter")
    fighter.current_hit_points = 1
    fighter.save()
    act(signed_in, fighter, action="feature_use", use=f"feature:{feature.pk}", roll="4")
    fighter.refresh_from_db()
    assert fighter.current_hit_points == 1 + 4 + 1
    assert fighter.resources.get(name="Second Wind").current_uses == 1


def test_warrior_of_the_gods_heals_the_rolled_total(signed_in, alice):
    barbarian = finished(alice, "barbarian")
    give(barbarian, "Warrior of the Gods", "Path of the Zealot", Warrior_of_the_Gods=(4, 4))
    feature = Feature.objects.get(name_en="Warrior of the Gods")
    barbarian.current_hit_points = 1
    barbarian.save()
    use = {"action": "feature_use", "use": f"feature:{feature.pk}"}
    assert act(signed_in, barbarian, **use, amount="2", total="30").status_code == 400  # > 2 x 12
    assert act(signed_in, barbarian, **use, amount="2", total="15").status_code == 200
    barbarian.refresh_from_db()
    assert barbarian.current_hit_points == min(16, barbarian.hit_point_maximum)
    assert barbarian.resources.get(name="Warrior of the Gods").current_uses == 2
