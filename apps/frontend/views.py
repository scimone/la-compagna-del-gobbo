from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.frontend.entries_render import (
    render_class_features,
    render_entries,
    render_key_value_table,
    render_subclasses,
    render_trait_cards,
)
from apps.rules.models import Feature
from apps.rules.services import background as background_service
from apps.rules.services import class_ as class_service
from apps.rules.services import feat as feat_service
from apps.rules.services import rule as rule_service
from apps.rules.services import species as species_service
from apps.rules.services import spell as spell_service

# Species menu art is keyed by "reprinted" 2024 slugs where they diverge from the plain
# species name used in the art filenames (e.g. `elf-xphb` -> `elf-grey.png`).
_SPECIES_IMAGE_SLUGS = {"elf-xphb": "elf"}


def _menu_image_url(folder: str, slug: str) -> str | None:
    """Static URL for a `static/images/<folder>/<slug>-grey.png` menu button image, or None if
    no such artwork exists yet (not every Class/Species row has one, e.g. Aasimar).
    """
    filename = f"{slug}-grey.png"
    if not (settings.BASE_DIR / "static" / "images" / folder / filename).exists():
        return None
    return static(f"images/{folder}/{filename}")


def index(request):
    return render(request, "frontend/index.html")


def world(request):
    return render(
        request,
        "frontend/world.html",
        {"page_title": _("World"), "back_url": reverse("index")},
    )


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


def _section(heading, html, *, open=True):
    """One (heading, html, open) entry for `_detail_page`'s `sections` - a collapsible
    `<details>` block in detail.html. `open=False` for sections long enough that showing them
    expanded by default buries the rest of the page (e.g. a Class's per-level features or
    subclasses) - everything else defaults open since it's usually short enough to just read.
    """
    return (heading, html, open)


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
        sections.append(_section(_("Equipment"), render_entries(equipment)))
    if bg.lore:
        sections.append(_section(_("Lore"), render_entries(bg.lore)))

    return _detail_page(request, bg.name, "world-backgrounds", facts, sections)


# --- Classes --------------------------------------------------------------------------------


def world_classes(request):
    items = [
        {
            "name": c.name,
            "detail": c.short_description,
            "url": reverse("world-class-detail", args=[c.pk]),
            "image": _menu_image_url("classes", c.id),
        }
        for c in class_service.list_classes()
    ]
    return _list_page(request, "Classes", items)


def world_class_detail(request, pk):
    klass = class_service.get_class(pk)
    subclasses = list(
        klass.subclasses.order_by("name").prefetch_related(
            Prefetch("levels__feature_rows", queryset=Feature.objects.order_by("pk"))
        )
    )

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
    facts.append((_("Page"), klass.page))

    sections = []
    if klass.lore:
        sections.append(_section(_("Lore"), render_entries(klass.lore)))

    sections.append(
        _section(_("Features by Level"), render_class_features(klass.features), open=False)
    )

    if subclasses:
        sections.append(_section(_("Subclasses"), render_subclasses(subclasses), open=False))

    levels = list(klass.levels.order_by("level"))
    if levels:
        headers = list(levels[0].columns.keys())
        rows = [lvl.columns for lvl in levels]
        sections.append(_section(_("Level Progression"), render_key_value_table(rows, headers)))

    return _detail_page(request, klass.name, "world-classes", facts, sections)


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

    sections = [_section(_("Description"), render_entries(feat.entries))]

    return _detail_page(request, feat.name, "world-feats", facts, sections)


# --- Species ---------------------------------------------------------------------------------


def world_species(request):
    items = [
        {
            "name": s.name,
            "detail": s.short_description,
            "url": reverse("world-species-detail", args=[s.pk]),
            "image": _menu_image_url("species", _SPECIES_IMAGE_SLUGS.get(s.id, s.id)),
        }
        for s in species_service.list_species()
    ]
    return _list_page(request, "Species", items)


def world_species_detail(request, pk):
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
        sections.append(_section(_("Lore"), render_entries(species.lore)))
    if species.entries:
        sections.append(_section(_("Traits"), render_trait_cards(species.entries)))

    return _detail_page(request, species.name, "world-species", facts, sections)


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

    sections = [_section(_("Description"), render_entries(spell.entries))]
    if spell.entries_higher_level:
        sections.append(_section(_("At Higher Levels"), render_entries(spell.entries_higher_level)))

    return _detail_page(request, spell.name, "world-spells", facts, sections)


# --- Rules -----------------------------------------------------------------------------------
# No dedicated browsing list for `rules.Rule` (that's not one of the seven categories asked
# for) - this page only exists as the landing spot for `{@variantrule ...}` links found inside
# other pages' text (see `apps.frontend.entries_render`), so "back" returns to the World hub
# rather than to any one specific list.


def world_rule_detail(request, pk):
    rule = rule_service.get_rule(pk)
    facts = [(_("Page"), rule.page)]
    sections = [_section(_("Description"), render_entries(rule.entries))]
    return _detail_page(request, rule.name, "world-overview", facts, sections)
