from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.frontend.entries_render import (
    render_class_features,
    render_entries,
    render_handbook_section,
    render_key_value_table,
    render_starting_equipment,
    render_subclasses,
    render_trait_cards,
)
from apps.rules.models import Feature
from apps.rules.services import background as background_service
from apps.rules.services import class_ as class_service
from apps.rules.services import feat as feat_service
from apps.rules.services import handbook as handbook_service
from apps.rules.services import rule as rule_service
from apps.rules.services import species as species_service
from apps.rules.services import spell as spell_service

# Species menu art is keyed by filename where it diverges from the Species' own id - empty now
# that `db/species.json`'s ids no longer carry a source suffix to diverge from (`Species.id` is
# plain `slugify(name)` post-migration, e.g. "elf", matching the art filenames directly) - kept as
# a dict (not removed) since a future reprint could reintroduce the same kind of divergence.
_SPECIES_IMAGE_SLUGS: dict[str, str] = {}

# Background menu art is keyed by filename where it diverges from the Background's own id
# (e.g. "scribe" -> "scriber.jpeg").
_BACKGROUND_IMAGE_SLUGS = {"scribe": "scriber"}

_ABILITY_NAMES = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}
_SIZE_CODES = {
    "T": "Tiny",
    "S": "Small",
    "M": "Medium",
    "L": "Large",
    "H": "Huge",
    "G": "Gargantuan",
}


def _format_ability_choice(raw_list):
    """`Background.ability_scores`: a list of alternative weighted spreads (see the model's
    docstring) - e.g. "Constitution +2, Intelligence +1 or Constitution +1, Intelligence +1,
    Wisdom +1".
    """
    alternatives = []
    for alt in raw_list or []:
        weighted = ((alt.get("choose") or {}).get("weighted")) or {}
        names = [_ABILITY_NAMES.get(c, c) for c in weighted.get("from", [])]
        weights = weighted.get("weights", [])
        pieces = [f"{n} +{w}" for n, w in zip(names, weights, strict=False)]
        if pieces:
            alternatives.append(", ".join(pieces))
    return " or ".join(alternatives)


def _format_flag_grant(raw_list):
    """A flat/choice proficiency-grant list shared by `Class.armor_proficiencies`/
    `weapon_proficiencies`/`tool_proficiencies` and `Background.tools` - each entry is either a
    plain `{"name": true}` flag or an ad hoc placeholder+count/filter shape.
    """
    parts = []
    for entry in raw_list or []:
        for key, value in entry.items():
            if value is True:
                parts.append(key.capitalize())
            elif isinstance(value, int):
                parts.append(f"{_('Choose')} {value}: {key}")
            elif isinstance(value, dict):
                parts.append(key.capitalize())
    return ", ".join(parts)


def _format_prerequisite(raw_list):
    """`Feat.prerequisite`/`OptionalFeature.prerequisite`: a structured list of `{level, ability,
    feature, proficiency, otherSummary}` entries - see `Feat`'s docstring.
    """
    alternatives = []
    for entry in raw_list or []:
        bits = []
        if "level" in entry:
            bits.append(f"{_('Level')} {entry['level']}")
        if "ability" in entry:
            bits.append(
                ", ".join(
                    f"{_ABILITY_NAMES.get(code, code)} {score}+"
                    for a in entry["ability"]
                    for code, score in a.items()
                )
            )
        if "feature" in entry:
            bits.append(", ".join(entry["feature"]))
        if "proficiency" in entry:
            bits.append(
                ", ".join(
                    key.capitalize() for p in entry["proficiency"] for key, val in p.items() if val
                )
            )
        if "otherSummary" in entry:
            summary = entry["otherSummary"]
            bits.append(summary.get("entrySummary") or summary.get("entry", ""))
        alternatives.append(", ".join(b for b in bits if b))
    return " or ".join(a for a in alternatives if a)


def _format_size(codes: list[str] | None) -> str:
    return "/".join(_SIZE_CODES.get(c, c) for c in codes or [])


def _format_creature_types(codes: list[str] | None) -> str:
    return ", ".join(c.capitalize() for c in codes or [])


def _format_casting_time(raw_list):
    parts = []
    for entry in raw_list or []:
        text = f"{entry.get('number', '')} {entry.get('unit', '')}".strip()
        if entry.get("condition"):
            text = f"{text}, {entry['condition']}"
        parts.append(text)
    return ", ".join(parts)


def _format_range(range_data):
    if not range_data:
        return ""
    distance = range_data.get("distance") or {}
    if distance.get("amount") is not None:
        return f"{distance['amount']} {distance.get('type', '')}".strip()
    return (range_data.get("type") or "").capitalize()


def _format_components(components):
    if not components:
        return ""
    letters = [label for label, key in [("V", "v"), ("S", "s")] if components.get(key)]
    material = components.get("m")
    if material:
        letters.append("M")
        if isinstance(material, dict) and material.get("text"):
            return f"{', '.join(letters)} ({material['text']})"
    return ", ".join(letters)


def _format_duration(raw_list):
    parts = []
    for entry in raw_list or []:
        duration_type = entry.get("type", "")
        if duration_type == "instant":
            text = _("Instantaneous")
        elif duration_type == "permanent":
            text = _("Until dispelled")
        elif duration_type == "timed":
            timed = entry.get("duration") or {}
            text = f"{timed.get('amount', '')} {timed.get('type', '')}".strip()
        else:
            text = duration_type.capitalize()
        if entry.get("concentration"):
            text = f"{_('Concentration')}, {_('up to')} {text}"
        parts.append(text)
    return ", ".join(parts)


def _menu_image_url(folder: str, filename: str) -> str | None:
    """Static URL for a `static/images/<folder>/<filename>` menu button image, or None if no
    such artwork exists yet (not every row has one, e.g. the Aasimar species).
    """
    if not (settings.BASE_DIR / "static" / "images" / folder / filename).exists():
        return None
    return static(f"images/{folder}/{filename}")


def index(request):
    # No standalone welcome screen - land directly on the leftmost bottom-nav destination.
    return redirect("characters-overview")


def world(request):
    # No standalone hub screen - land directly on the leftmost World tab.
    return redirect("world-backgrounds")


def _placeholder(request, title, back_url_name: str | None = None):
    # No back button by default: `characters_overview` (the only caller) is the leftmost
    # bottom-nav destination and `/` redirects straight to it, so there's no longer a
    # meaningful "back" target - pointing one at `index` would just bounce straight back here.
    context = {"page_title": _(title)}
    if back_url_name:
        context["back_url"] = reverse(back_url_name)
    return render(request, "frontend/overview.html", context)


def characters_overview(request):
    return _placeholder(request, "Characters")


def _list_page(
    request,
    title,
    items,
    back_url_name: str | None = "world-overview",
    world_tabs=False,
    image_vignette=False,
):
    context = {
        "page_title": _(title),
        "items": items,
        "world_tabs": world_tabs,
        "image_vignette": image_vignette,
    }
    if back_url_name:
        context["back_url"] = reverse(back_url_name)
    return render(request, "frontend/list.html", context)


def _section(heading, html, *, open=True):
    """One (heading, html, open) entry for `_detail_page`'s `sections` - a collapsible
    `<details>` block in detail.html. `open=False` for sections long enough that showing them
    expanded by default buries the rest of the page (e.g. a Class's per-level features or
    subclasses) - everything else defaults open since it's usually short enough to just read.
    """
    return (heading, html, open)


def _detail_page(
    request,
    title,
    back_url_name,
    facts,
    sections=(),
    body=None,
    plain_sections=(),
    tabs=None,
    active_tab=None,
):
    return render(
        request,
        "frontend/detail.html",
        {
            "page_title": title,
            "back_url": reverse(back_url_name),
            "facts": facts,
            "sections": sections,
            "body": body,
            "plain_sections": plain_sections,
            "tabs": tabs,
            "active_tab": active_tab,
        },
    )


def _active_tab(request, tabs, default: str) -> str:
    """Resolve the `?tab=` query param against a page's own `tabs` keys, falling back to
    `default` for a missing/unknown value instead of erroring - lets a stale/hand-typed link
    still land on a real tab rather than a blank page.
    """
    requested = request.GET.get("tab")
    valid_keys = {key for key, _label in tabs}
    return requested if requested in valid_keys else default


# --- Handbook ----------------------------------------------------------------------------


def handbook_overview(request):
    items = [
        {
            "name": section.name,
            "detail": f"{_('Page')} {section.page}",
            "url": reverse("handbook-section-detail", args=[section.pk]),
        }
        for section in handbook_service.list_sections()
    ]
    return _list_page(request, "Handbook", items, back_url_name="index")


def handbook_section_detail(request, pk):
    section = handbook_service.get_section(pk)
    facts = [(_("Page"), section.page)]
    body = render_handbook_section(section.entries)
    return _detail_page(request, section.name, "handbook-overview", facts, body=body)


# --- Backgrounds --------------------------------------------------------------------------


def world_backgrounds(request):
    items = [
        {
            "name": b.name,
            "url": reverse("world-background-detail", args=[b.pk]),
            "image": _menu_image_url(
                "backgrounds", f"{_BACKGROUND_IMAGE_SLUGS.get(b.id, b.id)}.jpeg"
            ),
        }
        for b in background_service.list_backgrounds()
    ]
    # No back button: `world-overview` (the default) now redirects straight back here (the
    # leftmost World tab), which would otherwise just bounce back to this same page.
    return _list_page(
        request, "Backgrounds", items, back_url_name=None, world_tabs=True, image_vignette=True
    )


def world_background_detail(request, pk):
    bg = background_service.get_background(pk)
    starting_equipment = bg.starting_equipment_options.select_related("item").order_by(
        "option", "pk"
    )

    facts = [(_("Ability Scores"), _format_ability_choice(bg.ability_scores))]
    skill_names = ", ".join(s.name for s in bg.skills.all())
    if skill_names:
        facts.append((_("Skills"), skill_names))
    if bg.tools:
        facts.append((_("Tools"), _format_flag_grant(bg.tools)))
    if bg.feat:
        facts.append((_("Feat"), bg.feat.name))
    if starting_equipment:
        facts.append((_("Starting Equipment"), render_starting_equipment(starting_equipment)))
    facts.append((_("Page"), bg.page))

    sections = []
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
            "image": _menu_image_url("classes", f"{c.id}-grey.png"),
        }
        for c in class_service.list_classes()
    ]
    return _list_page(request, "Classes", items, world_tabs=True)


def world_class_detail(request, pk):
    klass = class_service.get_class(pk)

    tabs = [("about", _("About")), ("levels", _("Levels")), ("subclasses", _("Subclasses"))]
    active_tab = _active_tab(request, tabs, default="about")

    facts = []
    plain_sections = []
    body = None

    if active_tab == "about":
        facts = [
            (_("Hit Die"), klass.hit_die.upper()),
            (_("Primary Ability"), klass.primary_ability_display),
            (_("Saving Throws"), klass.saving_throws_display),
        ]
        if klass.armor_proficiencies:
            facts.append((_("Armor Proficiencies"), _format_flag_grant(klass.armor_proficiencies)))
        if klass.weapon_proficiencies:
            facts.append(
                (_("Weapon Proficiencies"), _format_flag_grant(klass.weapon_proficiencies))
            )
        if klass.tool_proficiencies:
            facts.append((_("Tool Proficiencies"), _format_flag_grant(klass.tool_proficiencies)))
        starting_equipment = klass.starting_equipment_options.select_related("item").order_by(
            "option", "pk"
        )
        if starting_equipment:
            facts.append((_("Starting Equipment"), render_starting_equipment(starting_equipment)))
        facts.append((_("Page"), klass.page))

        if klass.lore:
            plain_sections.append((_("Lore"), render_entries(klass.lore)))

        levels = list(klass.levels.order_by("level"))
        if levels:
            # Spell slots/cantrips/prepared-or-known counts are their own dedicated `ClassLevel`
            # fields now (see the model's docstring), not part of the leftover `columns` blob -
            # merge them into the same display table rather than leaving them invisible on caster
            # classes.
            max_slot_level = max(
                (i for lvl in levels for i, n in enumerate(lvl.spell_slots, start=1) if n),
                default=0,
            )
            # Proficiency bonus follows the level directly (same formula for every
            # class/character, not something the source stores per class) - the PHB's class
            # tables print it anyway, so this table would look broken next to the official ones
            # without it.
            class_features = Feature.objects.filter(class_level__klass=klass).order_by("pk")
            features_by_level: dict[int, list[Feature]] = {}
            for feature in class_features:
                features_by_level.setdefault(feature.class_level.level, []).append(feature)

            rows = []
            for lvl in levels:
                row = {
                    _("Level"): lvl.level,
                    _("Proficiency Bonus"): f"+{2 + (lvl.level - 1) // 4}",
                    _("Features"): {
                        "type": "features",
                        "items": [
                            # The Features by Level cards this links to live on the Levels tab,
                            # not this (About) page, so the link needs that tab's own URL, not
                            # just a same-page `#feature-{pk}` fragment.
                            {"name": f.name, "href": f"?tab=levels#feature-{f.pk}"}
                            for f in features_by_level.get(lvl.level, [])
                        ],
                    },
                }
                row.update(lvl.columns)
                if lvl.cantrips_known is not None:
                    row[_("Cantrips Known")] = lvl.cantrips_known
                if lvl.spells_known_or_prepared is not None:
                    row[_("Spells")] = lvl.spells_known_or_prepared
                for spell_level in range(1, max_slot_level + 1):
                    idx = spell_level - 1
                    slots = lvl.spell_slots[idx] if idx < len(lvl.spell_slots) else 0
                    row[f"{_('Spell Slots')} {spell_level}"] = slots or ""
                rows.append(row)
            headers = list({key: None for row in rows for key in row}.keys())
            plain_sections.append((_("Level Progression"), render_key_value_table(rows, headers)))

    elif active_tab == "levels":
        class_features = list(Feature.objects.filter(class_level__klass=klass).order_by("pk"))
        body = render_class_features(class_features)

    elif active_tab == "subclasses":
        subclasses = list(
            klass.subclasses.order_by("name").prefetch_related(
                Prefetch("levels__feature_rows", queryset=Feature.objects.order_by("pk"))
            )
        )
        if subclasses:
            body = render_subclasses(subclasses)

    return _detail_page(
        request,
        klass.name,
        "world-classes",
        facts,
        body=body,
        plain_sections=plain_sections,
        tabs=tabs,
        active_tab=active_tab,
    )


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
    return _list_page(request, "Feats", items, world_tabs=True)


def world_feat_detail(request, pk):
    feat = feat_service.get_feat(pk)

    facts = [(_("Category"), feat.category)]
    if feat.prerequisite:
        facts.append((_("Prerequisite"), _format_prerequisite(feat.prerequisite)))
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
            "image": _menu_image_url("species", f"{_SPECIES_IMAGE_SLUGS.get(s.id, s.id)}-grey.png"),
        }
        for s in species_service.list_species()
    ]
    return _list_page(request, "Species", items, world_tabs=True)


def world_species_detail(request, pk):
    species = species_service.get_species(pk)

    tabs = [("about", _("About")), ("traits", _("Traits"))]
    active_tab = _active_tab(request, tabs, default="about")

    facts = []
    plain_sections = []
    body = None

    if active_tab == "about":
        facts = [
            (_("Size"), _format_size(species.size)),
            (_("Speed"), f"{species.speed} ft."),
            (_("Creature Type"), _format_creature_types(species.creature_types)),
        ]
        if species.darkvision:
            facts.append((_("Darkvision"), f"{species.darkvision} ft."))
        facts.append((_("Page"), species.page))

        if species.lore:
            plain_sections.append((_("Lore"), render_entries(species.lore)))

    elif active_tab == "traits":
        if species.entries:
            body = render_trait_cards(species.entries)

    return _detail_page(
        request,
        species.name,
        "world-species",
        facts,
        body=body,
        plain_sections=plain_sections,
        tabs=tabs,
        active_tab=active_tab,
    )


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
    return _list_page(request, "Spells", items, world_tabs=True)


def world_spell_detail(request, pk):
    spell = spell_service.get_spell(pk)
    level_value = _("Cantrip") if spell.level == 0 else spell.level

    facts = [
        (_("Level"), level_value),
        (_("School"), spell.school),
        (_("Casting Time"), _format_casting_time(spell.casting_time)),
        (_("Range"), _format_range(spell.range)),
        (_("Components"), _format_components(spell.components)),
        (_("Duration"), _format_duration(spell.duration)),
    ]
    if spell.concentration:
        facts.append((_("Concentration"), _("Yes")))
    if spell.ritual:
        facts.append((_("Ritual"), _("Yes")))
    saving_throws = ", ".join(a.name for a in spell.saving_throw_abilities.all())
    if saving_throws:
        facts.append((_("Saving Throw"), saving_throws))
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
