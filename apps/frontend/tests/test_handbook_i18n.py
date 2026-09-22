import re

import pytest
from django.core.management import call_command

from apps.rules.management.commands.import_rules_data import Command as ImportCommand


@pytest.fixture
def handbook(db):
    ImportCommand()._import_handbook()


def _get(client, url, language):
    client.cookies["django_language"] = language
    return client.get(url).content.decode()


def test_handbook_section_renders_in_italian(client, handbook):
    html = _get(client, "/handbook/095/", "it")

    assert "Danni e guarigione" in html
    assert "Tiri salvezza contro morte" in html
    assert "Saggezza (Medicina) con CD 10" in html  # `{@dc 10}` reads "CD 10", not just "10"


def test_handbook_section_renders_in_english(client, handbook):
    html = _get(client, "/handbook/095/", "en")

    assert "Damage and Healing" in html
    assert "Death Saving Throws" in html
    assert "DC 10" in html


def test_sections_without_italian_text_are_not_served_in_either_language(client, handbook):
    for language in ("it", "en"):
        # a chapter (never a section), "Rules Glossary" and "Player or DM?"
        for section_id in ("007", "008", "009"):
            client.cookies["django_language"] = language
            assert client.get(f"/handbook/{section_id}/").status_code == 404


def test_handbook_overview_lists_the_same_sections_in_both_languages(client, handbook):
    italian = _get(client, "/handbook/", "it")
    english = _get(client, "/handbook/", "en")

    assert "Combattimento" in italian
    assert "Dadi" in italian
    assert "Combat" in english
    assert "Dice" in english
    # "Rules Glossary" (a real nav entry here, listing the `Rule` catalog - see
    # `handbook_rules_glossary()`) isn't the source's own dropped static-prose section of the
    # same name (see `test_sections_without_italian_text_are_not_served_in_either_language`) -
    # both keep the same English label on purpose, so its Italian counterpart is checked instead.
    assert "Glossario" in italian
    assert "Glossary" in english
    assert "Rules Glossary" not in english and "Glossario delle regole" not in italian
    for html in (italian, english):
        assert "Player or DM?" not in html


def test_handbook_chapters_and_glossary_sit_in_tabs_and_sections_show_their_page(client, handbook):
    for language, name in (("it", "Glossario"), ("en", "Glossary")):
        html = _get(client, "/handbook/", language)
        before_main, main = html.split("<main>", 1)
        # Chapters/Glossary sit in a tab strip above the results, not a button in the contents
        assert "world-tabs" in before_main and name in before_main
        _before, chapters = main.split('<details class="chapter-group"', 1)
        # every section has a page icon and a "Page N" line, the number no longer on the icon
        assert chapters.count('<span class="page-icon"') == chapters.count("<li")
        assert re.search(r'<div class="item-detail">(Page|Pagina) \d+</div>', chapters)
        assert "page-number" not in chapters


def test_handbook_overview_groups_the_sections_under_a_toggle_heading_per_chapter(client, handbook):
    expected = {
        "en": ["Playing the Game", "Character Origins", "Feats", "Equipment", "Spells"],
        "it": [
            "Come si gioca",
            "Origini dei personaggi",
            "Talenti",
            "Equipaggiamento",
            "Incantesimi",
        ],
    }
    for language, names in expected.items():
        html = _get(client, "/handbook/", language)

        groups = re.findall(
            r'<details class="chapter-group" data-chapter="(\w+)" open>\s*<summary>(.*?)</summary>'
            r"(.*?)</details>",
            html,
            re.S,
        )
        assert [name for _key, name, _body in groups] == names
        assert [key for key, _name, _body in groups] == ["007", "11d", "130", "133", "154"]
        by_name = {name: body for _key, name, body in groups}
        # each section's button sits under its own chapter's heading
        assert 'href="/handbook/095/"' in by_name[names[0]]  # Damage and Healing
        assert 'href="/handbook/136/"' in by_name[names[3]]  # Weapons
        assert 'href="/handbook/158/"' in by_name[names[4]]  # Casting Spells
        assert 'href="/handbook/136/"' not in by_name[names[0]]


def test_the_srd_chapters_render_in_both_languages(client, handbook):
    weapons_en = _get(client, "/handbook/136/", "en")
    assert "Weapons" in weapons_en
    assert "Mastery Properties" in weapons_en
    assert "Cleave" in weapons_en
    weapons_it = _get(client, "/handbook/136/", "it")
    assert "Armi" in weapons_it
    assert "Proprietà di padronanza" in weapons_it
    assert "Doppio fendente" in weapons_it  # "Cleave"

    coins_en = _get(client, "/handbook/134/", "en")
    assert "Copper Piece (CP)" in coins_en and "Selling Equipment" in coins_en
    coins_it = _get(client, "/handbook/134/", "it")
    assert "Moneta di rame (mr)" in coins_it and "Vendere l&#x27;equipaggiamento" in coins_it

    spells_it = _get(client, "/handbook/158/", "it")
    assert "CD 15" in spells_it  # `{@dc 15}` in "Identifying an Ongoing Spell"
    assert "DC 15" in _get(client, "/handbook/158/", "en")


def test_spells_named_in_the_new_chapters_link_to_their_spell_page(client, db):
    call_command("import_rules_data")

    html = _get(client, "/handbook/158/", "it")

    assert 'href="/world/spells/magic-missile/">dardo incantato</a>' in html
    assert 'href="/world/spells/magic-missile/">Magic Missile</a>' in _get(
        client, "/handbook/158/", "en"
    )


def test_hand_translated_classes_intro_carries_the_traduzione_badge_only_in_italian(
    client, handbook
):
    italian = _get(client, "/handbook/12b/", "it")
    title = italian.split("<h1", 1)[1].split("</h1>", 1)[0]
    assert "Classi dei personaggi" in title and "Traduzione</span>" in title
    # each of the four toggle headings is badged as well
    summaries = re.findall(r"<summary>(.*?)</summary>", italian, re.S)
    assert len(summaries) == 4
    assert all("Traduzione</span>" in summary for summary in summaries)
    assert "Caratteristica primaria" in summaries[0]

    english = _get(client, "/handbook/12b/", "en")
    assert "Character Classes" in english
    assert "Traduzione</span>" not in english

    # ... and the button on the overview
    overview = _get(client, "/handbook/", "it")
    assert re.search(r'Classi dei personaggi\s*<span class="self-translated-badge"', overview)
    assert overview.count("Traduzione</span>") == 1
    assert "Traduzione</span>" not in _get(client, "/handbook/", "en")


def test_sections_taken_from_the_italian_srd_carry_no_traduzione_badge(client, handbook):
    for section_id in ("136", "158", "125", "134", "095"):
        assert "Traduzione</span>" not in _get(client, f"/handbook/{section_id}/", "it")


def test_worked_examples_are_removed_in_both_languages(client, handbook):
    for language in ("it", "en"):
        html = _get(client, "/handbook/043/", language)
        assert "Social Interaction Example" not in html
        assert "Ismark" not in html  # the example's dialogue


def test_skills_table_is_fully_translated(client, handbook):
    html = _get(client, "/handbook/036/", "it")

    assert "Acrobazia" in html
    assert "Furtività" in html
    assert "Sfuggi all&#x27;attenzione altrui" in html or "Sfuggi all'attenzione altrui" in html
    assert "Segui le tracce" in html


@pytest.fixture
def catalogs(db):
    call_command("import_rules_data")


def test_rules_glossary_lists_every_rule_and_links_to_its_own_detail_page(client, catalogs):
    # `handbook/rules-glossary/` must be routed before the `handbook/<slug:pk>/` catch-all in
    # urls.py, or this URL would 404 there instead (it doesn't match any real HandbookSection id).
    glossary = _get(client, "/handbook/rules-glossary/", "en")
    assert '<span class="item-name">Advantage</span>' in glossary
    assert 'href="/world/rules/advantage/"' in glossary

    # Same detail page the `{@variantrule ...}` tags elsewhere on the site already link to.
    detail = _get(client, "/world/rules/advantage/", "en")
    assert "<h1" in detail and "Advantage" in detail
    assert "<h2>Description</h2>" in detail


def test_spell_page_and_english_name_search_work_from_the_italian_site(client, catalogs):
    page = _get(client, "/world/spells/fireball/", "it")
    assert "Palla di fuoco" in page

    found = _get(client, "/world/spells/?q=Fireball", "it")  # English name, Italian site
    assert "Palla di fuoco" in found
    found = _get(client, "/world/spells/?q=palla", "en")  # Italian name, English site
    assert "Fireball" in found


def test_class_and_species_pages_render_in_italian(client, catalogs):
    assert "Barbaro" in _get(client, "/world/classes/barbarian/", "it")
    assert "Ira" in _get(client, "/world/classes/barbarian/?tab=levels", "it")
    assert "Dragonide" in _get(client, "/world/species/dragonborn/", "it")
    assert "Scurovisione" in _get(client, "/world/species/dragonborn/?tab=traits", "it")


def test_grung_is_badged_homebrew_in_both_languages_instead_of_translated(client, catalogs):
    for language in ("it", "en"):
        for url in ("/world/species/", "/world/species/grung/", "/world/species/grung/?tab=traits"):
            html = _get(client, url, language)
            assert "Homebrew</span>" in html
            assert "Traduzione</span>" not in html.split("<h1", 1)[1].split("</h1>", 1)[0]
        # the Traits tab and the About tab's Lore heading carry no translation badge either
        assert "Traduzione</span>" not in _get(client, "/world/species/grung/?tab=traits", language)
        assert "Traduzione</span>" not in _get(client, "/world/species/grung/", language)
    # an official species never gets it, and Aasimar (hand-translated, but official) keeps its own
    assert "Homebrew</span>" not in _get(client, "/world/species/dwarf/", "it")
    assert "Traduzione</span>" in _get(client, "/world/species/aasimar/", "it")


def test_class_level_table_headers_and_units_are_translated_in_italian(client, catalogs):
    html = _get(client, "/world/classes/monk/", "it")

    # column headers translated from the source's English column names
    assert "Punti concentrazione" in html
    assert "Arti marziali" in html
    assert "Movimento senza armatura" in html
    # a Monk's Unarmored Movement bonus (feet in the source) shows in meters
    assert "+3 m" in html  # level 2: +10 ft.
    assert "+4,5 m" in html  # level 6: +15 ft.
    assert "+10 ft." not in html
    assert "+15 ft." not in html


def test_class_level_table_stays_imperial_in_english(client, catalogs):
    html = _get(client, "/world/classes/monk/", "en")

    assert "Unarmored Movement" in html
    assert "+10 ft." in html
    assert "Punti concentrazione" not in html


def test_species_speed_and_darkvision_show_in_metres_on_the_italian_site(client, catalogs):
    html = _get(client, "/world/species/elf/", "it")
    assert "9 m" in html
    assert "30 ft." not in html

    html = _get(client, "/world/species/dwarf/", "it")
    assert "36 m" in html  # Darkvision 120 ft.


def test_species_speed_and_darkvision_stay_imperial_in_english(client, catalogs):
    html = _get(client, "/world/species/elf/", "en")
    assert "30 ft." in html


def test_spell_range_shows_in_metric_on_the_italian_site(client, catalogs):
    # Fireball's range is 150 feet in the source
    html = _get(client, "/world/spells/fireball/", "it")
    assert "45 metri" in html
    assert "150 feet" not in html

    html = _get(client, "/world/spells/fireball/", "en")
    assert "150 feet" in html


def test_spell_range_filter_shows_metric_labels_on_the_italian_site(client, catalogs):
    html = _get(client, "/world/spells/", "it")
    assert "45 metri" in html

    html = _get(client, "/world/spells/", "en")
    assert "150 feet" in html


def test_spell_school_casting_time_and_classes_are_translated_in_italian(client, catalogs):
    # Divine Smite: an Evocation spell (translated "Invocazione" - the classic Italian D&D
    # swap with Conjuration/"Evocazione"), a Bonus Action with a translated reaction-style
    # condition whose {@variantrule} tag still resolves to a real link, cast by Paladins.
    html = _get(client, "/world/spells/divine-smite/", "it")
    assert "Invocazione" in html
    assert "Evocation" not in html
    assert "1 azione bonus, che compi subito dopo aver colpito" in html
    assert '<a href="/world/rules/unarmed-strike/">colpo senz&#x27;armi</a>' in html
    assert '<a href="/world/classes/paladin/">Paladino</a>' in html
    assert "Bonus Action" not in html

    html = _get(client, "/world/spells/divine-smite/", "en")
    assert "Evocation" in html
    assert "1 bonus action, which you take immediately after hitting" in html
    assert '<a href="/world/classes/paladin/">Paladin</a>' in html

    # Summon Fiend: a Conjuration spell (translated "Evocazione"), cast by Warlocks.
    html = _get(client, "/world/spells/summon-fiend/", "it")
    assert "Evocazione" in html
    assert "Conjuration" not in html

    # Wish: cast by both Sorcerers and Wizards - every class in `Spell.classes` is translated
    # and linked, not just the first.
    html = _get(client, "/world/spells/wish/", "it")
    assert (
        '<a href="/world/classes/sorcerer/">Stregone</a>, <a href="/world/classes/wizard/">Mago</a>'
    ) in html


def test_artificer_is_dropped_entirely_from_spell_classes(client, catalogs):
    # `db_old/spells.json` (the only source for `Spell.classes`/`subclasses`, see Spell's
    # docstring) names Acid Splash's casters as Artificer, Sorcerer and Wizard - Artificer isn't
    # one of this project's Class rows and is dropped at import time, at the project owner's
    # request, rather than shown as an unlinked class name.
    html = _get(client, "/world/spells/acid-splash/", "it")
    assert '<a href="/world/classes/sorcerer/">Stregone</a>' in html
    assert '<a href="/world/classes/wizard/">Mago</a>' in html
    assert "Artefice" not in html
    assert "Artificer" not in html

    html = _get(client, "/world/spells/acid-splash/", "en")
    assert '<a href="/world/classes/sorcerer/">Sorcerer</a>' in html
    assert "Artificer" not in html


def test_spell_filters_show_translated_school_class_and_casting_time_labels(client, catalogs):
    html = _get(client, "/world/spells/", "it")
    assert "Invocazione" in html
    assert "Evocazione" in html
    assert "Abiurazione" in html
    assert "azione bonus" in html
    assert "10 minuti" in html
    assert "Paladino" in html

    html = _get(client, "/world/spells/", "en")
    assert "Evocation" in html
    assert "Conjuration" in html
    assert "Bonus Action" in html
    assert "10 Minutes" in html
    assert "Paladin" in html


def test_english_fallback_text_shows_metric_measurements_on_the_italian_site(client, catalogs):
    # Every spell has Italian text by now, so force one row back into the "no Italian text yet"
    # state this test targets: its body still mentions a distance ("10 feet"), which should read
    # metric on the Italian site even though the sentence itself stays English.
    from apps.rules.models import Spell

    Spell.objects.filter(pk="thorn-whip").update(entries_it=None)

    html = _get(client, "/world/spells/thorn-whip/", "it")
    assert "3 meters" in html
    assert "10 feet" not in html

    html = _get(client, "/world/spells/thorn-whip/", "en")
    assert "10 feet" in html


def test_class_ability_and_proficiency_facts_are_translated_in_italian(client, catalogs):
    html = _get(client, "/world/classes/fighter/", "it")
    assert "Destrezza o Forza" in html  # Primary Ability - an "or" pair
    assert "Costituzione, Forza" in html  # Saving Throws
    assert "Pesante, Leggera, Media, Scudo" in html  # Armor Proficiencies
    assert "Strength" not in html
    assert "Heavy" not in html

    html = _get(client, "/world/classes/paladin/", "it")
    assert "Carisma e Forza" in html  # Primary Ability - an "and" pair


def test_class_ability_and_proficiency_facts_stay_english(client, catalogs):
    html = _get(client, "/world/classes/fighter/", "en")
    assert "Dexterity or Strength" in html
    assert "Constitution, Strength" in html
    assert "Heavy, Light, Medium, Shield" in html


def test_class_weapon_proficiency_categories_are_translated_in_italian(client, catalogs):
    html = _get(client, "/world/classes/monk/", "it")
    assert "Tutte, Semplici" in html
    assert "Simple" not in html

    html = _get(client, "/world/classes/monk/", "en")
    assert "All, Simple" in html


def test_background_ability_scores_use_translated_ability_names(client, catalogs):
    html = _get(client, "/world/backgrounds/acolyte/", "it")
    assert "Intelligenza +2, Saggezza +1 o Intelligenza +1, Saggezza +1, Carisma +1" in html
    assert "Intelligence" not in html

    html = _get(client, "/world/backgrounds/acolyte/", "en")
    assert "Intelligence +2, Wisdom +1 or Intelligence +1, Wisdom +1, Charisma +1" in html


def test_background_named_tool_proficiency_resolves_through_equipment_translation(client, catalogs):
    # Wayfarer's tool proficiency is Thieves' Tools - a real, already-translated Equipment row,
    # not a bare category code.
    html = _get(client, "/world/backgrounds/wayfarer/", "it")
    assert "Arnesi da scasso" in html

    html = _get(client, "/world/backgrounds/wayfarer/", "en")
    assert "Thieves" in html


def test_background_tool_choice_placeholders_read_as_words_in_both_languages(client, catalogs):
    # These previously showed the source's bare camelCase key ("anyArtisansTool") verbatim -
    # fixed for English too, not just Italian.
    html = _get(client, "/world/backgrounds/artisan/", "it")
    assert "uno strumento da artigiano" in html
    assert "anyArtisansTool" not in html

    html = _get(client, "/world/backgrounds/artisan/", "en")
    assert "an artisan" in html  # ...&#x27;s tool - escaped apostrophe
    assert "anyArtisansTool" not in html

    assert "uno strumento musicale" in _get(client, "/world/backgrounds/entertainer/", "it")
    assert "un gioco" in _get(client, "/world/backgrounds/guard/", "it")


def test_species_size_and_creature_type_are_translated_in_italian(client, catalogs):
    html = _get(client, "/world/species/human/", "it")
    assert "Piccola/Media" in html
    assert "Umanoide" in html
    assert "Small" not in html
    assert "Humanoid" not in html

    html = _get(client, "/world/species/human/", "en")
    assert "Small/Medium" in html
    assert "Humanoid" in html


def test_feat_category_is_translated_in_italian(client, catalogs):
    html = _get(client, "/world/feats/ability-score-improvement/", "it")
    assert "Generale" in html

    # Alert is an Origin feat.
    html = _get(client, "/world/feats/alert/", "it")
    assert "Origini" in html

    # The category filter's displayed labels are translated - its underlying `value="..."`
    # attributes correctly stay the raw English category (matching a Feat's own DB column,
    # same as every other checklist/pill filter in this project), so this only checks the
    # labels a person actually reads.
    html = _get(client, "/world/feats/", "it")
    assert "Stile di combattimento" in html
    assert "Dono epico" in html

    html = _get(client, "/world/feats/ability-score-improvement/", "en")
    assert "General" in html


def test_background_list_shows_a_one_line_description(client, catalogs):
    html = _get(client, "/world/backgrounds/", "it")
    assert "Un devoto servitore di un tempio e della sua fede." in html

    html = _get(client, "/world/backgrounds/", "en")
    assert "A devoted servant of a temple and its faith." in html


def _item_name_html(html: str, name: str) -> str:
    """The `<span class="item-name">...</span>` block for a list item named `name` - so a badge
    check doesn't accidentally spill into a neighboring item's own markup.
    """
    match = re.search(rf'<span class="item-name">{re.escape(name)}.*?</span>', html, re.S)
    assert match, f"{name!r} not found as a list item-name"
    return match.group(0)


def test_list_pages_show_the_translated_badge_next_to_a_hand_translated_title(client, catalogs):
    # Actor (a feat) and Artisan (a background) are both fully hand-translated, including their
    # `name` - the World list pages should flag them the same way their detail pages do.
    html = _get(client, "/world/feats/", "it")
    assert _BADGE in _item_name_html(html, "Attore")

    html = _get(client, "/world/feats/", "en")
    assert "Attore" not in html  # English site shows the English name instead
    assert _BADGE not in html

    html = _get(client, "/world/backgrounds/", "it")
    assert _BADGE in _item_name_html(html, "Artigiano")

    # Alert (an SRD feat, officially translated) shows no badge.
    html = _get(client, "/world/feats/", "it")
    assert _BADGE not in _item_name_html(html, "Allerta")


_BADGE = '<span class="self-translated-badge"'


def test_self_translated_pages_show_the_badge_only_in_italian(client, catalogs):
    # Actor has no official (SRD) Italian source: both its name and its entries are hand-
    # translated, so the badge shows next to the title *and* next to "Description".
    html = _get(client, "/world/feats/actor/", "it")
    assert html.count(_BADGE) == 2
    assert "Traduzione</span>" in html
    assert "Traduzione non ufficiale" not in html  # shortened label, not the old longer one

    html = _get(client, "/world/feats/actor/", "en")
    assert _BADGE not in html

    # Alert is one of the SRD-sourced feats, translated from the official source.
    html = _get(client, "/world/feats/alert/", "it")
    assert _BADGE not in html


def test_self_translated_badge_only_marks_the_specific_hand_translated_block(client, catalogs):
    # Elf is entirely SRD-sourced except its Lore (PHB-only flavor text, hand-translated for this
    # project since the SRD never covers it) - the badge must sit next to "Lore" specifically,
    # not the page title, since the title's own name is official.
    html = _get(client, "/world/species/elf/", "it")
    body = html.split("<body>", 1)[1]
    header, _, rest = body.partition('<div class="facts">')
    assert _BADGE not in header  # the title ("Elfo") is official
    assert rest.count(_BADGE) == 1  # only the Lore heading is hand-translated
    assert "Ambientazione" in rest  # the Lore section itself still renders

    html = _get(client, "/world/species/elf/", "en")
    assert _BADGE not in html


def test_self_translated_badge_shows_on_individual_feature_and_subclass_cards(client, catalogs):
    # Path of the Zealot (and its "Divine Fury" feature) has no official Italian source either.
    html = _get(client, "/world/classes/barbarian/?tab=subclasses", "it")
    assert html.count(_BADGE) >= 2  # subclass block + at least one of its feature cards

    html = _get(client, "/world/classes/barbarian/?tab=subclasses", "en")
    assert _BADGE not in html

    # The same Class's About tab isn't about Path of the Zealot at all, but its own Lore section
    # is hand-translated (PHB-only, every class), so exactly that heading gets the badge - the
    # page title ("Barbaro", official) and the other About facts don't.
    html = _get(client, "/world/classes/barbarian/", "it")
    body = html.split("<body>", 1)[1]
    header, _, rest = body.partition('<div class="facts">')
    assert _BADGE not in header
    assert rest.count(_BADGE) == 1
