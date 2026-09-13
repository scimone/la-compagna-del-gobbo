from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.frontend.entries_render import render_entries, render_key_value_table
from apps.rules.services import background as background_service
from apps.rules.services import class_ as class_service
from apps.rules.services import feat as feat_service
from apps.rules.services import feature as feature_service
from apps.rules.services import species as species_service
from apps.rules.services import spell as spell_service


def index(request):
    return render(request, "frontend/index.html")


def world(request):
    return render(request, "frontend/world.html", {"back_url": reverse("index")})


def _placeholder(request, title, back_url_name="index"):
    return render(
        request,
        "frontend/overview.html",
        {"page_title": _(title), "back_url": reverse(back_url_name)},
    )


def characters_overview(request):
    return _placeholder(request, "Characters")


def handbook_overview(request):
    return _placeholder(request, "Handbook")


def _list_page(request, title, items):
    return render(
        request,
        "frontend/list.html",
        {"page_title": _(title), "back_url": reverse("world-overview"), "items": items},
    )


def _detail_page(request, title, back_url_name, facts, sections):
    return render(
        request,
        "frontend/detail.html",
        {
            "page_title": title,
            "back_url": reverse(back_url_name),
            "facts": facts,
            "sections": sections,
        },
    )


# --- Backgrounds --------------------------------------------------------------------------


def world_backgrounds(request):
    items = [
        {"name": b.name, "url": reverse("world-background-detail", args=[b.pk])}
        for b in background_service.list_backgrounds()
    ]
    return _list_page(request, "Backgrounds", items)


def _extract_named_entry(entries, name):
    """Background.entries is always a single list-hang-notitle block whose items are named
    Ability Scores:/Feat:/Skill Proficiencies:/Tool Proficiency:/Equipment: (verified against
    every one of the 16 XPHB backgrounds) - everything but Equipment duplicates a plain field
    we already store, so this pulls out just the one piece that isn't captured elsewhere.
    """
    if not entries:
        return None
    top = entries[0]
    if isinstance(top, dict) and top.get("type") == "list":
        for item in top.get("items", []):
            if isinstance(item, dict) and item.get("name") == name:
                return item
    return None


def world_background_detail(request, pk):
    bg = background_service.get_background(pk)
    equipment = _extract_named_entry(bg.entries, "Equipment:")

    facts = [(_("Ability Scores"), bg.ability_scores), (_("Skills"), bg.skills)]
    if bg.tools:
        facts.append((_("Tools"), bg.tools))
    if bg.feat:
        facts.append((_("Feat"), bg.feat))
    facts.append((_("Page"), bg.page))

    sections = []
    if equipment:
        sections.append((_("Equipment"), render_entries(equipment)))
    if bg.lore:
        sections.append((_("Lore"), render_entries(bg.lore)))

    return _detail_page(request, bg.name, "world-backgrounds", facts, sections)


# --- Classes --------------------------------------------------------------------------------


def world_classes(request):
    items = [
        {
            "name": c.name,
            "detail": f"{c.hit_die.upper()} · {c.primary_ability}",
            "url": reverse("world-class-detail", args=[c.pk]),
        }
        for c in class_service.list_classes()
    ]
    return _list_page(request, "Classes", items)


def world_class_detail(request, pk):
    klass = class_service.get_class(pk)
    subclasses = list(klass.subclasses.order_by("name").values_list("name", flat=True))

    facts = [
        (_("Hit Die"), klass.hit_die.upper()),
        (_("Primary Ability"), klass.primary_ability),
        (_("Saving Throws"), klass.saving_throws),
    ]
    if klass.armor_proficiencies:
        facts.append((_("Armor Proficiencies"), klass.armor_proficiencies))
    if klass.weapon_proficiencies:
        facts.append((_("Weapon Proficiencies"), klass.weapon_proficiencies))
    if klass.tool_proficiencies:
        facts.append((_("Tool Proficiencies"), klass.tool_proficiencies))
    if subclasses:
        facts.append((_("Subclasses"), ", ".join(subclasses)))
    facts.append((_("Page"), klass.page))

    sections = []
    if klass.lore:
        sections.append((_("Lore"), render_entries(klass.lore)))

    feature_nodes = [
        {
            "type": "entries",
            "name": f"{f['name']} — {_('Level')} {f['level']}",
            "entries": f["entries"],
        }
        for f in klass.features
    ]
    sections.append((_("Features by Level"), render_entries(feature_nodes)))

    levels = list(klass.levels.order_by("level"))
    if levels:
        headers = list(levels[0].columns.keys())
        rows = [lvl.columns for lvl in levels]
        sections.append((_("Level Progression"), render_key_value_table(rows, headers)))

    return _detail_page(request, klass.name, "world-classes", facts, sections)


# --- Class Features --------------------------------------------------------------------------


def world_class_features(request):
    items = []
    for f in feature_service.list_class_features():
        klass_name = f.klass.name if f.klass_id else f.subclass_level.subclass.klass.name
        detail = f"{klass_name} · {_('Level')} {f.level}" if f.level else klass_name
        items.append(
            {
                "name": f.name,
                "detail": detail,
                "url": reverse("world-class-feature-detail", args=[f.pk]),
            }
        )
    return _list_page(request, "Class Features", items)


def world_class_feature_detail(request, pk):
    feature = feature_service.get_feature(pk)
    if feature.klass_id:
        klass_name = feature.klass.name
        subclass_name = None
    else:
        klass_name = feature.subclass_level.subclass.klass.name
        subclass_name = feature.subclass_level.subclass.name

    facts = [(_("Class"), klass_name)]
    if subclass_name:
        facts.append((_("Subclass"), subclass_name))
    if feature.level:
        facts.append((_("Level"), feature.level))

    sections = [(_("Description"), render_entries(feature.entries))]

    return _detail_page(request, feature.name, "world-class-features", facts, sections)


# --- Feats -----------------------------------------------------------------------------------


def world_feats(request):
    items = [
        {
            "name": f.name,
            "detail": f.category,
            "url": reverse("world-feat-detail", args=[f.pk]),
        }
        for f in feat_service.list_feats()
    ]
    return _list_page(request, "Feats", items)


def world_feat_detail(request, pk):
    feat = feat_service.get_feat(pk)

    facts = [(_("Category"), feat.category)]
    if feat.prerequisite:
        facts.append((_("Prerequisite"), feat.prerequisite))
    facts.append((_("Page"), feat.page))

    sections = [(_("Description"), render_entries(feat.entries))]

    return _detail_page(request, feat.name, "world-feats", facts, sections)


# --- Races (Species) --------------------------------------------------------------------------


def world_races(request):
    items = [
        {"name": s.name, "detail": s.size, "url": reverse("world-race-detail", args=[s.pk])}
        for s in species_service.list_species()
    ]
    return _list_page(request, "Races", items)


def world_race_detail(request, pk):
    species = species_service.get_species(pk)

    facts = [
        (_("Size"), species.size),
        (_("Speed"), species.speed),
        (_("Creature Type"), species.creature_type),
    ]
    for label, value in [
        (_("Fly Speed"), species.fly_speed),
        (_("Swim Speed"), species.swim_speed),
        (_("Climb Speed"), species.climb_speed),
    ]:
        if value:
            facts.append((label, f"{value} ft."))
    facts.append((_("Page"), species.page))

    sections = []
    if species.lore:
        sections.append((_("Lore"), render_entries(species.lore)))
    if species.entries:
        sections.append((_("Traits"), render_entries(species.entries)))

    return _detail_page(request, species.name, "world-races", facts, sections)


def world_subraces(request):
    # The 2024 rules dropped subraces as a mechanic - db/species.json has no XPHB entry with a
    # parent species set, so this is honestly empty rather than a placeholder.
    return _list_page(request, "Subraces", [])


# --- Spells ----------------------------------------------------------------------------------


def world_spells(request):
    items = []
    for s in spell_service.list_spells():
        level_text = _("Cantrip") if s.level == 0 else f"{_('Level')} {s.level}"
        items.append(
            {
                "name": s.name,
                "detail": f"{level_text} · {s.school}",
                "url": reverse("world-spell-detail", args=[s.pk]),
            }
        )
    return _list_page(request, "Spells", items)


def world_spell_detail(request, pk):
    spell = spell_service.get_spell(pk)
    level_value = _("Cantrip") if spell.level == 0 else spell.level

    facts = [
        (_("Level"), level_value),
        (_("School"), spell.school),
        (_("Casting Time"), spell.casting_time),
        (_("Range"), spell.range),
        (_("Components"), spell.components),
        (_("Duration"), spell.duration),
    ]
    if spell.concentration:
        facts.append((_("Concentration"), _("Yes")))
    if spell.ritual:
        facts.append((_("Ritual"), _("Yes")))
    if spell.classes:
        facts.append((_("Classes"), ", ".join(spell.classes)))
    facts.append((_("Page"), spell.page))

    sections = [(_("Description"), render_entries(spell.entries))]
    if spell.entries_higher_level:
        sections.append((_("At Higher Levels"), render_entries(spell.entries_higher_level)))

    return _detail_page(request, spell.name, "world-spells", facts, sections)
