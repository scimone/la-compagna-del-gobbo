"""A finished character's page: the sheet the player uses at the table.

`character_detail` renders one page holding every tab (Stats, Abilities, Features, Spellbook,
Inventory, Proficiencies, Biography); a script switches between them without reloading, `?tab=`
only picks the one shown first. Each tab has a `_<tab>` function below that turns rows and
`derived_stats.compute()` into plain dicts for its template, so the templates hold no logic.

`character_act` is the one endpoint the sheet's script posts to (tick a death save, spend a
slot, change the HP, ...). Every rule for those changes lives in `characters.services.play`; the
view only translates HTTP into calls and answers with the state the script needs to redraw.
"""

from math import ceil

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, pgettext_lazy
from django.views.decorators.http import require_GET, require_POST

from apps.builder import tables
from apps.builder.class_spec import CLASS_SPEC
from apps.builder.resolvers.proficiency import WeaponProficiency
from apps.builder.services import creation, derived_stats, land, progression
from apps.characters.models import Character, CharacterChoice
from apps.characters.services import access, play, portrait
from apps.frontend import translations, units
from apps.frontend.character_views import (
    _DESCRIBERS,
    _card_line,
    _damage_text,
    _gold_label,
    _step_url,
    _warning_text,
)
from apps.frontend.entries_render import machine_translated_badge
from apps.frontend.views import (
    _CASTING_TIME_FILTER_LABELS,
    _SCHOOL_LABELS,
    _SIZE_LABELS,
    _SPECIES_IMAGE_SLUGS,
    _WEAPON_CATEGORY_LABELS,
    _class_name,
    _format_feat_category,
    _menu_image_url,
    _option_class_id,
    _option_type_label,
    _pick_translation,
)
from apps.rules.models import (
    Ability,
    Class,
    ClassLevel,
    Equipment,
    EquipmentProperty,
    EquipmentType,
    Feat,
    Feature,
    Mastery,
    OptionalFeature,
    Skill,
    Species,
    Spell,
)
from apps.rules.services import spell as spell_service

TABS = (
    ("stats", gettext_lazy("Stats")),
    ("abilities", gettext_lazy("Abilities")),
    # Context: plain "Features" is already "Caratteristiche", the same as "Abilities" would be.
    ("features", pgettext_lazy("character sheet tab", "Features")),
    ("spellbook", gettext_lazy("Spellbook")),
    ("inventory", gettext_lazy("Inventory")),
    ("proficiencies", gettext_lazy("Proficiencies")),
    ("biography", gettext_lazy("Biography")),
)
DEFAULT_TAB = TABS[0][0]

#: The three-letter form of each ability, English then Italian (`_pick_translation` tables).
_ABILITY_ABBR = {
    "str": ("STR", "FOR"),
    "dex": ("DEX", "DES"),
    "con": ("CON", "COS"),
    "int": ("INT", "INT"),
    "wis": ("WIS", "SAG"),
    "cha": ("CHA", "CAR"),
}
#: Inventory sections, in display order, and which `EquipmentType` ids go into which.
_INVENTORY_SECTIONS = (
    ("weapons", gettext_lazy("Weapons"), ("m", "r")),
    ("armor", gettext_lazy("Armor"), ("la", "ma", "ha", "s")),
    ("tools", gettext_lazy("Tools"), ("t", "at", "gs", "ins")),
    ("misc", gettext_lazy("Misc Items"), ()),
)
#: The tool sections of the Proficiencies tab and which `EquipmentType` ids each lists. The first
#: takes every tool that is not a gaming set or an instrument (artisan's tools, thieves' tools...).
_TOOL_GROUPS = (
    (gettext_lazy("Tool Proficiencies"), ("at", "t")),
    (gettext_lazy("Gaming Sets"), ("gs",)),
    (gettext_lazy("Musical Instruments"), ("ins",)),
)
_ARMOR_CATEGORY_TYPES = {"light": "la", "medium": "ma", "heavy": "ha", "shield": "s"}
#: The coins shown in the pouch (electrum only appears once the character owns some).
_COINS = (
    ("copper", gettext_lazy("Copper"), gettext_lazy("CP")),
    ("silver", gettext_lazy("Silver"), gettext_lazy("SP")),
    ("gold", gettext_lazy("Gold"), gettext_lazy("GP")),
    ("platinum", gettext_lazy("Platinum"), gettext_lazy("PP")),
)
_ELECTRUM = ("electrum", gettext_lazy("Electrum"), gettext_lazy("EP"))
_CASTER_DIVISOR = {"full": 1, "1/2": 2, "artificer": 2, "1/3": 3}


def _describe_url(kind: str, pk) -> str:
    return reverse("character-describe", args=[kind, pk])


def _abbr(ability_id: str) -> str:
    return _pick_translation(_ABILITY_ABBR, ability_id)


# --- header and status strip ---------------------------------------------------------------------


def _header(character: Character, stats) -> dict:
    """What the Stats tab shows about the character's progress, and the portrait for the header."""
    next_xp = tables.XP_BY_LEVEL[stats.level] if stats.level < len(tables.XP_BY_LEVEL) else None
    floor = tables.XP_BY_LEVEL[stats.level - 1]
    xp = character.experience_points
    return {
        "level": stats.level,
        "xp": xp,
        "next_xp": next_xp,
        "can_level_up": progression.can_level_up(character),
        "xp_ready": progression.xp_ready(character),
        # How far along the way to the next level, for the Stats tab's bar (a character levelled
        # by milestone can sit outside its level's XP range, hence the clamp).
        "xp_progress": (
            round(max(0, min(1, (xp - floor) / (next_xp - floor))) * 100) if next_xp else 100
        ),
        "speed": units.distance(stats.speed),
        "passive_perception": stats.passive_perception,
        # The name in the URL changes with every upload, so a new picture is never a cached old one.
        "portrait": (
            f"{reverse('character-portrait', args=[character.pk])}?v={character.portrait.name}"
            if character.portrait
            else ""
        ),
        "portrait_frame": {
            "cx": character.portrait_cx,
            "cy": character.portrait_cy,
            "zoom": character.portrait_zoom,
        },
    }


def _recovery(character: Character, stats) -> dict | None:
    """Arcane / Natural Recovery at the Short Rest: what it is called, how many levels of slots it
    brings back, and the slot pools it may take from (a pact pool never; nothing above level 5)."""
    feature = play.slot_recovery(character)
    if feature is None:
        return None
    classes = list(character.classes.select_related("klass"))
    pools = [
        p
        for p in _slots(character, stats, classes)
        if p["key"].isdigit() and p["level"] <= play.SLOT_RECOVERY_MAX_LEVEL
    ]
    return {**feature, "pools": pools}


def _percent(part: int, whole: int) -> int:
    return round(max(0, min(1, part / whole)) * 100) if whole else 0


def _strip(character: Character, stats, items) -> dict:
    shield = next((i for i in items if i.equipment.type_id == play.SHIELD_TYPE), None)
    names = dict(Ability.objects.values_list("pk", "name"))
    return {
        "armor_class": stats.armor_class["value"],
        "shield_item": shield.pk if shield else None,
        "shield_worn": stats.armor_class["shield"],
        "initiative": stats.initiative,
        "con_modifier": stats.abilities["con"]["modifier"],
        "hp": character.current_hit_points,
        "max_hp": character.hit_point_maximum,
        "recovery": _recovery(character, stats),
        "hp_reduction": character.max_hit_points_reduction,
        "drained": bool(character.ability_reductions),
        "ability_reductions": [
            (key, names.get(key, key), int((character.ability_reductions or {}).get(key, 0)))
            for key in tables.ABILITIES
        ],
        "hp_percent": _percent(character.current_hit_points, character.hit_point_maximum),
        "temp_hp": character.temporary_hit_points,
        "hit_dice": [
            {
                "die": die,
                "total": hd["total"],
                "spent": hd["spent"],
                "left": hd["total"] - hd["spent"],
                # One pip per die, filled while it is still there (like the spell slots).
                "pips": [i < hd["total"] - hd["spent"] for i in range(hd["total"])],
            }
            for die, hd in stats.hit_dice.items()
        ],
        "death_rows": [
            ("successes", _("Successes"), "✓", character.death_save_successes),
            ("failures", _("Failures"), "✕", character.death_save_failures),
        ],
        "inspiration": character.inspiration,
        "resources": [
            {"pk": r.pk, "name": r.name, "current": r.current_uses, "max": r.max_uses}
            for r in character.resources.all()
        ],
    }


# --- abilities ---------------------------------------------------------------------------------


def _abilities(stats) -> dict:
    names = {a.id: a.name for a in Ability.objects.all()}
    return {
        "proficiency_bonus": stats.proficiency_bonus,
        "abilities": [
            {
                "id": a,
                "abbr": _abbr(a),
                "name": names.get(a, a),
                **stats.abilities[a],
                "save": stats.saving_throws[a],
            }
            for a in tables.ABILITIES
        ],
        "skills": [
            {
                "name": s.name,
                **stats.skills[s.id],
                "ability": _abbr(s.ability_id),  # after the ** so the short label wins over the id
            }
            for s in Skill.objects.select_related("ability").order_by("name")
        ],
    }


# --- features ----------------------------------------------------------------------------------


def _removal(can_edit: bool, source: str, kind: str, pk) -> dict:
    """The row's own "take this off the sheet" action (see `item.remove` in `_list_item.html`) -
    only for something the player added by hand, and only while they can edit this character."""
    if not (can_edit and source == play.FEATURE_SOURCE):
        return {}
    return {
        "remove": {
            "act": "feature_remove",
            "param": "feature",
            "id": f"{kind}:{pk}",
            "confirm": _("Remove this feature?"),
        }
    }


def _feature_row(f) -> dict:
    """One `rules.Feature` (a species trait, class feature or subclass feature) as a Features
    list row: the exact same shape `world_feats()` builds, linking to its own World page."""
    row = {
        "pk": f.pk,
        "kind": "feature",
        "name": f.name,
        "url": reverse("world-feature-detail", args=[f.pk]),
        "search": f"{f.name_en} {f.name_it}".lower(),
    }
    if f.species_id:
        return {
            **row,
            "properties": [_("Species"), f.species.name],
            "image": _menu_image_url(
                "features_species",
                f"{_SPECIES_IMAGE_SLUGS.get(f.species_id, f.species_id)}.jpg",
            ),
            "type": "species",
            "group": f.species_id,
        }
    if f.class_level_id:
        klass = f.class_level.klass
        return {
            **row,
            "properties": [_("Class"), klass.name, f"{_('Level')} {f.class_level.level}"],
            "image": _menu_image_url("features_classes", f"{klass.pk}.jpeg"),
            "type": "class",
            "group": klass.pk,
        }
    subclass = f.subclass_level.subclass
    return {
        **row,
        "properties": [
            _("Subclass"),
            subclass.name,
            f"{_('Level')} {f.subclass_level.level}",
        ],
        "image": _menu_image_url("features_subclasses", f"{subclass.klass_id}.jpg"),
        "image_class": "subclass-icon",
        "type": "subclass",
        "group": subclass.klass_id,
    }


def _feat_row(feat) -> dict:
    return {
        "pk": feat.pk,
        "name": feat.name,
        "properties": [_("Feat"), _format_feat_category(feat.category)],
        "url": reverse("world-feat-detail", args=[feat.pk]),
        "image": _menu_image_url(
            "feats", f"{feat.category.split(' (')[0].lower().replace(' ', '_')}.jpeg"
        ),
        "type": "feat",
        "search": f"{feat.name_en} {feat.name_it}".lower(),
    }


def _option_row(option) -> dict:
    klass_id = _option_class_id(option)
    return {
        "pk": option.pk,
        "kind": "option",
        "name": option.name,
        "properties": [_("Option"), _option_type_label(option.feature_type)],
        "url": reverse("world-option-detail", args=[option.pk]),
        "image": _menu_image_url("features_classes", f"{klass_id}.jpeg") if klass_id else None,
        "type": "option",
        "search": f"{option.name_en} {option.name_it}".lower(),
    }


def _feature_items(character: Character, can_edit: bool = False) -> list[dict]:
    """Flat, alphabetical rows for the Features tab's own searchable/filterable list - the exact
    same row shape `world_feats()` builds (same `properties`, bookmarkable the same way - see
    `_features_tab()`), just limited to this character's own species traits, class features,
    subclass features, feats and options (invocations, maneuvers, ...), and each linking straight
    to its own World detail page. One the player added by hand also carries its own `remove`
    action (see `_removal()`).
    """
    items = []
    for cf in character.features.select_related(
        "feature__class_level__klass",
        "feature__subclass_level__subclass__klass",
        "feature__species",
    ):
        f = cf.feature
        if f.species_id or f.class_level_id or f.subclass_level_id:
            items.append({**_feature_row(f), **_removal(can_edit, cf.source, "feature", f.pk)})
    for cf in character.feats.select_related("feat"):
        items.append({**_feat_row(cf.feat), **_removal(can_edit, cf.source, "feat", cf.feat.pk)})
    for co in character.optional_features.select_related("optional_feature"):
        option = co.optional_feature
        items.append({**_option_row(option), **_removal(can_edit, co.source, "option", option.pk)})
    items.sort(key=lambda item: item["name"].casefold())
    return items


def _feature_type_filter(items: list[dict], always: bool = False) -> dict | None:
    """The Features tab's own Type pill row, limited to the kinds this character actually has (a
    filter with a single possible value would filter nothing - same convention as
    `_spell_filters()`). Built by hand rather than `views._pill_filter()`: there's no `request`
    query param behind this one, `character_sheet.js`'s `filterRows()` reads it client-side only,
    the same way it already does the spellbook's own filters.
    """
    labels = {
        "feat": _("Feats"),
        "class": _("Class Features"),
        "subclass": _("Subclass Features"),
        "species": _("Species Traits"),
        "option": _("Options"),
    }
    present = [kind for kind in labels if any(item["type"] == kind for item in items)]
    if len(present) <= 1 and not always:
        return None
    return {
        "kind": "radio",
        "name": "type",
        "label": _("Type"),
        "value": "",
        "options": [(kind, labels[kind]) for kind in present],
        "all_label": _("All"),
        "only": None,
    }


def _features_tab(request, character: Character, can_edit: bool = False) -> dict:
    """The character's features list. Bookmarking lives on the World lists only."""
    items = _feature_items(character, can_edit)
    type_filter = _feature_type_filter(items)
    return {
        "count": len(items),
        "items": items,
        "filters": [type_filter] if type_filter else [],
        "land_change": land.land_options(character) if can_edit else None,
    }


# --- spellbook ---------------------------------------------------------------------------------


def _slot_maximums(stats, classes) -> tuple[list[int], dict | None]:
    """`(slots by level, pact)`: the slots of the one class that has them, or - for a multiclass
    caster - the SRD's combined table (every full-caster level, half of half-casters' rounded up,
    a third of third-casters' rounded down)."""
    sources = [s for s in stats.spellcasting if s["source"].startswith("class:") and s["slots"]]
    pact = next((s["pact"] for s in stats.spellcasting if s["pact"]), None)
    if len(sources) <= 1:
        return (list(sources[0]["slots"]) if sources else []), pact
    by_class = {c.klass_id: c for c in classes}
    total = 0
    for source in sources:
        row = by_class[source["source"].removeprefix("class:")]
        divisor = _CASTER_DIVISOR.get(row.klass.caster_progression, 3)
        total += ceil(row.level / divisor) if divisor == 2 else row.level // divisor
    table = ClassLevel.objects.filter(
        klass__caster_progression="full", level=max(1, min(total, 20))
    ).first()
    return (list(table.spell_slots) if table and table.spell_slots else []), pact


def _slots(character: Character, stats, classes) -> list[dict]:
    """Every slot pool with its pips: `[{key, label, short_label, level, max, spent, pips}]`. The
    short label is what actually shows on its chip, next to the spell list's own level heading -
    just the level digit, or "P" for a pact pool - `label` remains for its tooltip and for screen
    readers. `level` is the spell level the pool's slots are spent on (a pact pool's own level,
    for one) - what groups it under the matching heading."""
    maximums, pact = _slot_maximums(stats, classes)
    spent = character.spell_slots_spent
    pools = [
        {
            "key": str(level),
            "label": f"{_('Level')} {level}",
            "short_label": str(level),
            "level": level,
            "max": count,
        }
        for level, count in enumerate(maximums, start=1)
        if count
    ]
    if pact:
        pools.append(
            {
                "key": "pact",
                "label": _("Pact Magic (level %(level)s)") % {"level": pact["level"]},
                "short_label": _("P"),
                "level": pact["level"],
                "max": pact["slots"],
            }
        )
    for pool in pools:
        pool["spent"] = min(int(spent.get(pool["key"], 0)), pool["max"])
        pool["left"] = pool["max"] - pool["spent"]
        pool["pips"] = [i < pool["left"] for i in range(pool["max"])]  # True = still available
    return pools


def _casting_sources(stats, classes) -> list[dict]:
    names = {c.klass_id: c.klass.name for c in classes}
    ability_names = {a.id: a.name for a in Ability.objects.all()}
    sources = []
    for entry in stats.spellcasting:
        kind, _sep, ident = entry["source"].partition(":")
        origin = (
            names.get(ident, "")
            if kind == "class"
            else {"species": _("Species")}.get(kind, _("Feat"))
        )
        sources.append(
            {
                "id": entry["source"],
                "ability": ability_names.get(entry["ability"], entry["ability"]),
                "origin": origin,
                "modifier": stats.abilities[entry["ability"]]["modifier"],
                "dc": entry["save_dc"],
                "attack": entry["attack_bonus"],
            }
        )
    return sources


def _spell_row(spell, status: str = "") -> dict:
    """One spell as a list row - in the "add a spell" sheet (`character_spells()`), and as the
    base `_spellbook_row()` builds on for the spellbook's own list. `level`/`school`/... are
    what the filter buttons compare against (see `_spell_filters()`)."""
    level_text = _("Cantrip") if spell.level == 0 else f"{_('Level')} {spell.level}"
    return {
        "key": f"spell-{spell.pk}",
        "id": spell.pk,
        "spell": spell,
        "name": spell.name,
        "search": f"{spell.name_en} {spell.name_it}".lower(),
        "detail": " · ".join(
            x for x in (level_text, _pick_translation(_SCHOOL_LABELS, spell.school), status) if x
        ),
        "image": _menu_image_url("spells", f"{spell.school.lower()}.jpeg"),
        "describe": _describe_url("spell", spell.pk),
        "level": spell.level,
        "school": spell.school,
        "classes": " ".join(spell.classes or []),
        "range": spell_service.range_kind(spell),
        "times": " ".join(spell_service.casting_time_keys(spell)),
        "saves": " ".join(a.id for a in spell.saving_throw_abilities.all()),
    }


def _spellbook_row(spell, status: str, removable: bool, cast: dict | None = None) -> dict:
    """One of this character's own known spells as a list row - the exact same look and
    click-through-to-its-own-page behavior as the World's own Spells list (`world_feats()`'s
    sibling, `world_spells()`), reusing `_spell_row()`'s already-computed fields rather than
    duplicating them. `removable` (only true for a spell the player added by hand, and only
    while they can edit this character) adds its own small "take this off the spellbook" action
    next to the bookmark button - see `item.remove` in `_list_item.html`.
    """
    row = _spell_row(spell, status)
    row["pk"] = spell.pk
    row["url"] = reverse("world-spell-detail", args=[spell.pk])
    # `_list_item.html`'s `filterRows()`-facing `data-*` attributes - the same values `_spell_row()`
    # already put in `classes`/`school`/`range`/`times`/`saves` (no `level`: the main spellbook
    # groups by level already, so filtering on it too would just repeat that grouping). Not
    # `search` here: `row["search"]` (from `_spell_row()`) already renders its own `data-search`
    # via `_list_item.html`'s dedicated `item.search` shortcut - repeating it under `data` too
    # would render the attribute twice.
    row["data"] = {
        "class": row["classes"],
        "school": row["school"],
        "range": row["range"],
        "time": row["times"],
        "save": row["saves"],
    }
    if cast:
        row["cast"] = {"id": spell.pk, "level": spell.level, **cast}
    if removable:
        row["remove"] = {
            "act": "spell_remove",
            "param": "spell",
            "id": spell.pk,
            "confirm": _("Remove this spell?"),
        }
    return row


def _prepared_limits(stats) -> dict[str, int]:
    """`{class id: how many spells it prepares}` for the classes that prepare spells."""
    return {
        e["source"].removeprefix("class:"): e["prepared"]
        for e in stats.spellcasting
        if e["source"].startswith("class:") and e.get("prepared")
    }


def _spellbook_rows(character: Character, can_edit: bool, limits: dict | None = None) -> list[dict]:
    rows = []
    limits = limits or {}
    natural_free = play.natural_free_cast_left(character)
    for cs in (
        character.spells.select_related("spell", "klass")
        .prefetch_related("spell__saving_throw_abilities")
        .order_by("spell__level", "spell__name")
    ):
        if cs.always_prepared:
            status = _("Always prepared")
        elif cs.prepared and cs.spell.level > 0:
            # The Prepared button already says so - only a read-only sheet has no button.
            status = "" if can_edit else _("Prepared")
        elif cs.in_spellbook:
            status = _("In spellbook")
        else:
            status = ""
        # A spell the player added by hand can be taken away again; the ones a class, species or
        # feat gave cannot.
        removable = can_edit and cs.source == play.SPELL_SOURCE
        # Cantrips and prepared spells can be cast (a slot for the latter); a ritual only sitting
        # in the spellbook can still be cast as a ritual.
        prepared = cs.prepared or cs.always_prepared
        cast = None
        if cs.spell.level == 0 or prepared or (cs.spell.ritual and cs.in_spellbook):
            cast = {
                "source": f"class:{cs.klass_id}" if cs.klass_id else "",
                "ritual": cs.spell.ritual,
                "slot": cs.spell.level > 0 and prepared,
                "free": (
                    (cs.free_cast and not cs.free_cast_used and cs.spell.level > 0)
                    or (natural_free and play.is_circle_spell(cs))
                ),
                "concentration": cs.spell.concentration,
            }
        row = _spellbook_row(cs.spell, status, removable, cast)
        # Level 1+ spells are prepared (SRD "Preparing Spells"); always-prepared ones and cantrips
        # are not the player's to switch. A caster's spell the class cannot prepare (a Wizard's
        # spell outside the spellbook) is not offered either.
        if can_edit and cs.spell.level > 0 and not cs.always_prepared:
            # Taking a class's spell off needs one of its changes (a long rest or a level opens
            # them) - until then the pill is shown but cannot be pressed.
            locked = (
                cs.prepared
                and cs.klass_id in limits
                and not character.spell_changes.get(cs.klass_id)
            )
            full = (
                not cs.prepared
                and cs.klass_id in limits
                and _prepared_count(character, cs.klass_id) >= limits[cs.klass_id]
            )
            # No Prepare button at all while the class has no room for another spell.
            if not full:
                row["prepare"] = {"spell": cs.spell.pk, "on": cs.prepared, "locked": locked}
        row["unprepared"] = cs.spell.level > 0 and not prepared
        rows.append(row)
    return rows


def _prepared_count(character: Character, class_id: str) -> int:
    return character.spells.filter(
        klass_id=class_id, prepared=True, always_prepared=False, spell__level__gt=0
    ).count()


def _max_spell_level(entry: dict) -> int:
    """The highest spell level a spellcasting entry (see `derived_stats._spellcasting`) casts."""
    levels = [n for n, count in enumerate(entry["slots"], start=1) if count]
    if entry["pact"]:
        levels.append(entry["pact"]["level"])
    return max(levels, default=0)


def _learnable_rows(character: Character, stats, classes, can_edit: bool, limits: dict) -> list:
    """The spells a class that prepares spells could prepare but the character has no row for yet
    (the whole class list up to the level it casts) - shown greyed out under the prepared ones.
    A class that keeps a spellbook (the Wizard) prepares from that book only, so adds none."""
    known = set(character.spells.values_list("spell_id", flat=True))
    names = {c.klass_id: getattr(c.klass, "name_en", c.klass.name) for c in classes}
    rows = []
    for entry in stats.spellcasting:
        kind, _sep, class_id = entry["source"].partition(":")
        if kind != "class" or class_id not in limits or class_id not in names:
            continue
        if character.spells.filter(klass_id=class_id, in_spellbook=True).exists():
            continue
        top = _max_spell_level(entry)
        full = _prepared_count(character, class_id) >= limits[class_id]
        for spell in (
            Spell.objects.filter(level__gte=1, level__lte=top)
            .prefetch_related("saving_throw_abilities")
            .order_by("level", "name")
        ):
            if spell.pk in known or names[class_id] not in (spell.classes or []):
                continue
            row = _spellbook_row(spell, "", False)
            row["unprepared"] = row["learnable"] = True
            if can_edit and not full:
                row["prepare"] = {
                    "spell": spell.pk,
                    "on": False,
                    "locked": False,
                    "klass": class_id,
                }
            rows.append(row)
            known.add(spell.pk)
    return rows


def _spell_filters(rows: list[dict]) -> list[dict]:
    """The World > Spells filter buttons, limited to what this character's spells actually use
    (a filter with a single possible value would filter nothing)."""
    saves = {a.id: a.name for a in Ability.objects.all()}

    def options(values, label_of):
        return [(v, label_of(v)) for v in values]

    levels = sorted({r["level"] for r in rows})
    classes = sorted({c for r in rows for c in r["classes"].split(" ") if c})
    schools = sorted({r["school"] for r in rows})
    ranges = sorted({r["range"] for r in rows if r["range"]}, key=spell_service.range_sort_key)
    times = [
        (key, _pick_translation(_CASTING_TIME_FILTER_LABELS, label))
        for key, label in spell_service.casting_time_options(r["spell"] for r in rows)
    ]
    used_saves = [a for a in saves if any(a in r["saves"].split(" ") for r in rows)]
    candidates = [
        (
            "level",
            _("Level"),
            options(levels, lambda n: _("Cantrip") if n == 0 else f"{_('Level')} {n}"),
        ),
        ("class", _("Class"), options(classes, _class_name)),
        ("school", _("School"), options(schools, lambda s: _pick_translation(_SCHOOL_LABELS, s))),
        ("range", _("Range"), options(ranges, units.range_label)),
        ("time", _("Casting Time"), times),
        ("save", _("Saving Throw"), options(used_saves, saves.get)),
    ]
    return [
        {"kind": "checkbox", "name": name, "label": label, "values": set(), "options": opts}
        for name, label, opts in candidates
        if len(opts) > 1
    ]


#: The SRD's "Spell Preparation by Class" table as a sentence, per (when, how many).
_PREPARATION_RULES = {
    ("rest", "any"): gettext_lazy("You can change any prepared spells after a long rest"),
    ("rest", 1): gettext_lazy("You can change one prepared spell after a long rest"),
    ("level", 1): gettext_lazy("You can change one prepared spell after gaining a level"),
}
_PREPARATION_OPEN = {
    "any": gettext_lazy("You can change any prepared spells now"),
    1: gettext_lazy("You can change one prepared spell now"),
}


_PREPARATION_HINT = gettext_lazy("Unprepare a spell above to make room for another")


def _preparation(character: Character, stats, classes) -> list[dict]:
    """Per class that prepares spells: how many it has prepared out of how many the class table
    allows (always-prepared spells and cantrips do not count), and the SRD's rule for changing -
    or, while the class has changes left (after a long rest or a level), that it can change now."""
    names = {c.klass_id: c.klass.name for c in classes}
    result = []
    for entry in stats.spellcasting:
        kind, _sep, class_id = entry["source"].partition(":")
        if kind != "class" or not entry.get("prepared"):
            continue
        count = character.spells.filter(
            klass_id=class_id, prepared=True, always_prepared=False, spell__level__gt=0
        ).count()
        left = character.spell_changes.get(class_id)
        rule = play.PREPARATION_CHANGES.get(class_id)
        result.append(
            {
                "class": names.get(class_id, class_id),
                "count": count,
                "limit": entry["prepared"],
                "can_change": bool(left),
                "text": (_PREPARATION_OPEN[left] if left else _PREPARATION_RULES.get(rule, "")),
                # A class at its limit has to unprepare something before it can prepare another.
                "hint": _PREPARATION_HINT if left and count >= entry["prepared"] else "",
            }
        )
    return result


def _finish_cast(cast: dict, sources: list[dict], slots: list[dict]) -> None:
    """Fill in what the cast dialog shows for one spell: the casting numbers of the spell's own
    class (a spell from a species or feat: the first non-class source, else the first), and
    whether a slot is left to cast it with - a cantrip or a ritual needs none."""
    source = next((s for s in sources if s["id"] == cast["source"]), None)
    if source is None:
        source = next((s for s in sources if not s["id"].startswith("class:")), None)
    source = source or (sources[0] if sources else {})
    cast["ability"] = source.get("ability", "")
    cast["modifier"] = f"{source.get('modifier', 0):+d}"
    cast["dc"] = source.get("dc", "")
    cast["attack"] = f"{source.get('attack', 0):+d}"
    cast["available"] = (
        cast["level"] == 0
        or cast["ritual"]
        or cast["free"]
        or any(p["level"] >= cast["level"] and p["left"] > 0 for p in slots)
    )


def _spellbook(request, character: Character, stats, classes, can_edit: bool) -> dict:
    limits = _prepared_limits(stats)
    rows = _spellbook_rows(character, can_edit, limits)
    rows += _learnable_rows(character, stats, classes, can_edit, limits)
    slots = _slots(character, stats, classes)
    sources = _casting_sources(stats, classes)
    for row in rows:
        cast = row.get("cast")
        if cast:
            _finish_cast(cast, sources, slots)
    # Grouped by level for the spell list's own sticky headings, each with the slot pool(s) spent
    # at that level next to it (there can be more than one - a Pact Magic pool lands wherever its
    # own level is, alongside a multiclass table's slots of that same level, if both exist). A
    # level with slots but no spells yet still gets a heading (just an empty one, below); a level
    # with spells but no slots (cantrips) gets a heading with no chip next to it.
    slots_by_level: dict[int, list[dict]] = {}
    for pool in slots:
        slots_by_level.setdefault(pool["level"], []).append(pool)
    spells_by_level: dict[int, list[dict]] = {}
    unprepared_by_level: dict[int, list[dict]] = {}
    for row in rows:
        by_level = unprepared_by_level if row["unprepared"] else spells_by_level
        by_level.setdefault(row["level"], []).append(row)
    groups = [
        {
            "level": level,
            "label": _("Cantrips") if level == 0 else f"{_('Level')} {level}",
            "slots": slots_by_level.get(level, []),
            "spells": spells_by_level.get(level, []),
        }
        for level in sorted(set(spells_by_level) | set(slots_by_level))
    ]
    # With unprepared spells below, the level 1+ groups form the "Prepared" block (its own heading,
    # which every spell level from 1 up falls under - cantrips are not prepared).
    if unprepared_by_level:
        leveled = [g for g in groups if g["level"] >= 1]
        if leveled:
            leveled[0]["block_start"] = True
            leveled[-1]["block_end"] = True
    # What the class could prepare but has not: the same level headings, no slots, below the rest.
    unprepared = [
        {
            "level": level,
            "label": f"{_('Level')} {level}",
            "slots": [],
            "spells": unprepared_by_level[level],
        }
        for level in sorted(unprepared_by_level)
    ]
    # The "Level" filter would just repeat the level groups above - not necessary, unlike the
    # World Spells list, which has no such grouping of its own.
    filters = [f for f in _spell_filters(rows) if f["name"] not in ("level", "class")]
    return {
        "sources": sources,
        "spell_groups": groups,
        "unprepared_groups": unprepared,
        "known_count": sum(1 for r in rows if not r.get("learnable")),
        "spells": rows,
        "spell_filters": filters,
        "preparation": _preparation(character, stats, classes),
    }


# --- inventory ---------------------------------------------------------------------------------


def _weight_text(pounds: float) -> str:
    return units.metricize_text(f"{pounds:g} lb.")


def _item_card(kind: str, row, pack_name: str = "") -> dict:
    """One line of the inventory: a catalog stack (`CharacterInventoryItem`) or a custom item."""
    custom = kind == "custom"
    if custom:
        name, unit_weight, unit_value, full = row.name, row.weight, row.value, row.valuable
    else:
        eq = row.equipment
        name, unit_weight, unit_value = eq.name, eq.weight, eq.value
        full = eq.type_id in play.FULL_VALUE_TYPES
    weight = (unit_weight or 0) * row.quantity
    # One line under the name, like a spell's "Cantrip · Divination": what the item does, then
    # what it weighs and costs, then where it came from.
    detail = []
    if custom and row.weapon_category:
        detail.append(_pick_translation(_WEAPON_CATEGORY_LABELS, row.weapon_category))
    if custom and row.type_label:
        detail.append(row.type_label)
    if not custom:
        if eq.damage_dice:
            detail.append(_damage_text(eq))
        if eq.range:
            detail.append(f"{_('Range')} {units.weapon_range(eq.range)}")
        if eq.type_id in play.BODY_ARMOR_TYPES and eq.ac:
            detail.append(f"{_('AC')} {eq.ac}")
        elif eq.type_id == play.SHIELD_TYPE and eq.ac:
            detail.append(f"{_('AC')} +{eq.ac}")
    if weight:
        detail.append(_weight_text(weight))
    if unit_value:
        detail.append(_gold_label(unit_value * row.quantity))
    if not custom and eq.attunement:
        detail.append(_("Attunement"))
    if pack_name:
        detail.append(_("from %(pack)s") % {"pack": pack_name})
    one = play.sale_price(unit_value, 1, full_value=full)
    everything = play.sale_price(unit_value, row.quantity, full_value=full)
    # The row's own quick-sell button always sells for *something* if the stack is worth anything
    # at all: one unit when that alone is worth a coin, otherwise the whole stack (a single cheap
    # item - a torch - rounds down to nothing sold on its own, but a stack of them isn't nothing).
    if one:
        quick_sell = {"quantity": 1, "price": _gold_label(one)}
    elif everything:
        quick_sell = {"quantity": row.quantity, "price": _gold_label(everything)}
    else:
        quick_sell = None
    return {
        "key": f"{kind}-{row.pk}",
        "kind": kind,
        "id": row.pk,
        "name": name,
        "quantity": row.quantity,
        "detail": " · ".join(detail),
        "weight": weight,
        "equipped": not custom and row.equipped,
        "wearable": not custom and eq.type_id in play.WEARABLE_TYPES,
        "section": row.section if custom else "",
        # The row opens the item's own page (`character_item()`): its description, and what the
        # player can do with it - quantity, sell, remove.
        "url": reverse(
            "character-custom-item" if custom else "character-stack-item",
            args=[row.character_id, row.pk],
        ),
        "full_value": full,
        "sell_one": _gold_label(one) if one else "",
        "sell_all": _gold_label(everything) if everything and row.quantity > 1 else "",
        "quick_sell": quick_sell,
    }


def _inventory(character: Character, stats) -> dict:
    rows = list(
        character.inventory_items.select_related("equipment__type", "parent__equipment").order_by(
            "equipment__name"
        )
    )
    packs = {r.parent_id for r in rows if r.parent_id}
    section_of = {t: key for key, _label, types in _INVENTORY_SECTIONS for t in types}
    sections = {
        key: {"key": key, "label": label, "cards": []} for key, label, _t in _INVENTORY_SECTIONS
    }
    total_weight = 0.0
    # A pack is not listed itself: its contents are, each saying which pack they came from.
    for row in rows:
        if row.pk in packs:
            continue
        pack_name = row.parent.equipment.name if row.parent_id else ""
        card = _item_card("catalog", row, pack_name)
        total_weight += card["weight"]
        card["warnings"] = (
            [_warning_text(w) for w in stats.item_warnings.get(row.equipment_id, [])]
            if row.equipped
            else []
        )
        sections[section_of.get(row.equipment.type_id, "misc")]["cards"].append(card)
    for row in character.custom_items.all():
        card = _item_card("custom", row)
        total_weight += card["weight"]
        sections[card["section"]]["cards"].append(card)
    for section in sections.values():
        section["cards"].sort(key=lambda c: c["name"].lower())
    return {
        "coins": _coins(character),
        "sections": [s for s in sections.values() if s["cards"]],
        "total_weight": _weight_text(total_weight) if total_weight else "",
    }


def _coins(character: Character) -> list[dict]:
    """The coin purse: the Inventory tab's pouch, and the "add an item" sheet's sticky one."""
    purse = getattr(character, "currency", None)
    coins = [
        {"key": key, "label": label, "abbr": abbr, "amount": getattr(purse, key, 0) if purse else 0}
        for key, label, abbr in _COINS
    ]
    if purse and purse.electrum:
        coins.insert(
            2,
            {
                "key": "electrum",
                "label": _ELECTRUM[1],
                "abbr": _ELECTRUM[2],
                "amount": purse.electrum,
            },
        )
    return coins


# --- proficiencies -----------------------------------------------------------------------------


def _chips(equipment) -> list[dict]:
    return [
        {"name": e.name, "describe": _describe_url("equipment", e.pk)}
        for e in sorted(equipment, key=lambda e: e.name)
    ]


def _weapon_groups(proficiency: WeaponProficiency) -> list[dict]:
    """One group per weapon grant, listing the weapons that grant really covers: "martial weapons
    with the Light property" is every martial weapon that has it."""
    weapons = list(
        Equipment.objects.filter(
            type_id__in=("m", "r"), weapon_category__in=("simple", "martial")
        ).prefetch_related("properties")
    )
    property_names = {p.id: p.name for p in EquipmentProperty.objects.all()}

    def category_label(category: str) -> str:
        return _pick_translation(_WEAPON_CATEGORY_LABELS, category)

    groups = []
    for category in sorted(proficiency.categories, reverse=True):  # simple before martial
        groups.append(
            {
                "title": _("%(category)s weapons") % {"category": category_label(category)},
                "chips": _chips(w for w in weapons if w.weapon_category == category),
            }
        )
    for category, property_ids in proficiency.filtered:
        if category in proficiency.categories:
            continue
        names = _(" or ").join(sorted(property_names.get(p, p) for p in property_ids))
        groups.append(
            {
                "title": _("%(category)s weapons with the %(property)s property")
                % {"category": category_label(category), "property": names},
                "chips": _chips(
                    w
                    for w in weapons
                    if w.weapon_category == category
                    and {p.id for p in w.properties.all()} & property_ids
                ),
            }
        )
    for name in sorted(proficiency.named):
        groups.append({"title": name.capitalize(), "chips": []})
    return groups


def _proficiencies(character: Character) -> dict:
    held = list(character.proficiencies.all())
    armor_types = {
        t.id: t.name for t in EquipmentType.objects.filter(id__in=_ARMOR_CATEGORY_TYPES.values())
    }
    armor = []
    for category in ("light", "medium", "heavy", "shield"):
        if ("armor", category) in {(p.category, p.name) for p in held}:
            type_id = _ARMOR_CATEGORY_TYPES[category]
            armor.append(
                {
                    "title": armor_types.get(type_id, category.capitalize()),
                    "chips": _chips(Equipment.objects.filter(type_id=type_id)),
                }
            )

    weapons = _weapon_groups(
        derived_stats.weapon_proficiency(p.name for p in held if p.category == "weapon")
    )

    mastery_choice = CharacterChoice.objects.filter(
        character=character, key="class.weapon_mastery"
    ).first()
    masteries = []
    for weapon in Equipment.objects.filter(
        id__in=(mastery_choice.value if mastery_choice else []) or []
    ).prefetch_related("masteries"):
        for mastery in weapon.masteries.all():
            masteries.append(
                {
                    "name": weapon.name,
                    "detail": mastery.name,
                    "describe": _describe_url("mastery", mastery.pk),
                }
            )
    masteries.sort(key=lambda m: m["name"])

    # After a Long Rest: one mastery weapon may be swapped for another the class could choose.
    swap = None
    if character.weapon_mastery_changes:
        offered = {}
        for class_id in character.weapon_mastery_changes:
            if class_id in CLASS_SPEC:
                offered.update({w.id: w.name for w in play.mastery_weapons(character, class_id)})
        chosen = (mastery_choice.value if mastery_choice else []) or []
        swap = {
            "current": sorted(
                ((w.id, w.name) for w in Equipment.objects.filter(id__in=chosen)),
                key=lambda t: t[1],
            ),
            "candidates": [
                (i, n) for i, n in sorted(offered.items(), key=lambda t: t[1]) if i not in chosen
            ],
        }

    tools = {
        e.id: e
        for e in Equipment.objects.filter(id__in=[p.name for p in held if p.category == "tool"])
    }
    tool_groups = []
    for title, type_ids in _TOOL_GROUPS:
        chips = _chips(e for e in tools.values() if e.type_id in type_ids)
        tool_groups.append({"title": title, "chips": chips})
    unknown = [p.name for p in held if p.category == "tool" and p.name not in tools]
    if unknown:
        tool_groups[0]["chips"] += [{"name": n.capitalize(), "describe": ""} for n in unknown]

    return {
        "armor": armor,
        "weapons": weapons,
        "masteries": masteries,
        "mastery_swap": swap,
        "tool_groups": tool_groups,
        "languages": sorted(
            cl.language.name for cl in character.languages.select_related("language")
        ),
    }


# --- identity and biography ---------------------------------------------------------------------


def _identity(character: Character, classes) -> dict:
    """Who the character is, in the header: background, class, species and size."""
    size = character.size or (
        character.species.size[0] if character.species and len(character.species.size) == 1 else ""
    )
    return {
        "background": character.background,
        "species": character.species,
        "size": _pick_translation(_SIZE_LABELS, size) if size else "",
        "multiclass": len(classes) > 1,
        "classes": [
            {
                "name": c.klass.name,
                "level": c.level,
                "subclass": c.subclass.name if c.subclass else "",
                "url": reverse("world-class-detail", args=[c.klass_id]),
            }
            for c in classes
        ],
    }


def shown_backstory(character: Character) -> tuple[str, bool]:
    """The backstory as the active language's reader sees it, and whether it is a translation."""
    return translations.translated_texts(
        "backstory", {character.pk: {"backstory": character.backstory}}
    )[character.pk]["backstory"]


def _biography(character: Character) -> dict:
    # Everyone, the owner's textarea included, reads the backstory in the active language:
    # machine-translated if it was written in the other one.
    story, translated = shown_backstory(character)
    return {
        "pictures": [
            {"id": p.pk, "url": reverse("character-gallery-picture", args=[character.pk, p.pk])}
            for p in character.pictures.all()
        ],
        "backstory": story,
        "backstory_badge": mark_safe(machine_translated_badge()) if translated else "",
        "alignment": next(
            (name for code, name, _abbr in tables.ALIGNMENTS if code == character.alignment), ""
        ),
    }


# --- the page ----------------------------------------------------------------------------------


def character_detail(request, pk):
    character = get_object_or_404(
        Character.objects.select_related("species", "background", "owner"), pk=pk
    )
    if not access.can_view(request.user, character):
        raise Http404
    if character.status == Character.STATUS_DRAFT:
        return redirect(_step_url(character, creation.get_state(character)["current"]))
    stats = derived_stats.compute(character)
    classes = list(character.classes.select_related("klass", "subclass"))
    items = list(character.inventory_items.select_related("equipment"))
    can_edit = access.can_edit(request.user, character)
    tab = request.GET.get("tab", "")
    response = render(
        request,
        "frontend/characters/detail.html",
        {
            "page_title": character.name,
            "back_url": reverse("characters-overview"),
            "character": character,
            "can_edit": can_edit,
            # Hit Dice are spent by resting; only the DM or an administrator sets them by hand.
            "can_edit_hit_dice": access.can_speak_as_dm(request.user),
            "can_edit_slots": access.can_speak_as_dm(request.user),
            "can_assign": access.is_admin(request.user),
            "can_reopen": access.is_admin(request.user) and creation.can_reopen(character),
            # Not `tabs`/`active_tab`: base.html draws its own `?tab=` strip for those names.
            "sheet_tabs": TABS,
            "sheet_tab": tab if tab in dict(TABS) else DEFAULT_TAB,
            "header": _header(character, stats),
            "strip": _strip(character, stats, items),
            "abilities": _abilities(stats),
            "features": _features_tab(request, character, can_edit),
            "spellbook": _spellbook(request, character, stats, classes, can_edit),
            "inventory": _inventory(character, stats),
            "proficiencies": _proficiencies(character),
            "identity": _identity(character, classes),
            "biography": _biography(character),
            # The "add an item" sheet's Buy confirmation is built client-side (its purse total has
            # to stay live across several buys, so it can't be a string rendered once at page load,
            # like the Sell ones are) - these are the pieces `character_sheet.js` fills in.
            "buy_fmt": {
                "gp": _("%(n)d gp"),
                "sp": _("%(n)d sp"),
                "cp": _("%(n)d cp"),
                "confirm": _("Buy for %(price)s?"),
                "left": _("You will have %(left)s left."),
            },
        },
    )
    add_never_cache_headers(response)
    return response


# --- the endpoint the sheet's script posts to --------------------------------------------------


def _int(post, name: str) -> int:
    try:
        return int(post.get(name, ""))
    except ValueError:
        raise ValueError(f"{name} is not a number") from None


def _slot_maximum(character: Character, key: str) -> int:
    stats = derived_stats.compute(character)
    classes = list(character.classes.select_related("klass"))
    return next((p["max"] for p in _slots(character, stats, classes) if p["key"] == key), 0)


def _act_hit_dice(character, post):
    die = post.get("die", "")
    hd = derived_stats.compute(character).hit_dice.get(die)
    if hd is None:
        raise ValueError(f"no {die} hit dice")
    play.set_hit_dice_spent(character, die, hd["spent"] + _int(post, "delta"))


def _act_short_rest(character, post):
    """`rolls=d10:6,d8:3`: the die and the result the player rolled for each Hit Die spent."""
    recover = {}
    for part in post.get("recover", "").split(","):
        if part:
            level, _sep, count = part.partition(":")
            recover[level] = int(count)
    rolls = []
    for part in post.get("rolls", "").split(","):
        if part:
            die, _sep, result = part.partition(":")
            rolls.append((die, int(result)))
    con = derived_stats.compute(character).abilities["con"]["modifier"]
    healed = play.short_rest(character, rolls, con, recover)
    message = _("Short rest taken")
    if healed:
        message += " - " + _("%(hp)d hit points regained") % {"hp": healed}
    return {"refresh": True, "message": message}


def _spell_change_prompt() -> str:
    return _("You can change your prepared spells now. Do you want to do it?")


def _act_long_rest(character, post):
    play.long_rest(character)
    result = {"refresh": True, "message": _("Long rest taken")}
    if character.spell_changes:
        result["prompt"] = _spell_change_prompt()
    elif character.weapon_mastery_changes:
        result["prompt"] = _(
            "You can change one of your Weapon Mastery weapons now. Do you want to do it?"
        )
        result["prompt_tab"] = "proficiencies"
    elif character.rest_choices.get("land"):
        result["prompt"] = _("You can choose a new land for Circle of the Land now. Do it?")
        result["prompt_tab"] = "features"
    return result


def _act_land_change(character, post):
    land.change_land(character, post.get("land", ""))
    return {"refresh": True, "message": _("Land changed")}


def _act_mastery_swap(character, post):
    play.swap_weapon_mastery(character, post.get("old", ""), post.get("new", ""))
    return {"refresh": True, "message": _("Weapon Mastery changed")}


def _act_resource(character, post):
    play.adjust_resource(character, _int(post, "id"), _int(post, "delta"))


def _act_slots(character, post):
    key = post.get("key", "")
    spent = int(character.spell_slots_spent.get(key, 0)) + _int(post, "delta")
    play.set_slots_spent(character, key, spent, _slot_maximum(character, key))


def _act_cast(character, post):
    """Cast a spell: which slot pool pays for it (`slot`), or as a ritual (`ritual=1`)."""
    spell = character.spells.select_related("spell").get(spell_id=post.get("spell", "")).spell
    key = post.get("slot", "")
    stats = derived_stats.compute(character)
    classes = list(character.classes.select_related("klass"))
    pool = next((p for p in _slots(character, stats, classes) if p["key"] == key), None)
    free = post.get("free") == "1"
    if pool is None and spell.level > 0 and post.get("ritual") != "1" and not free:
        raise ValueError("no such spell slot")
    play.cast_spell(
        character,
        spell.pk,
        slot_key=key,
        slot_max=pool["max"] if pool else 0,
        slot_level=pool["level"] if pool else 0,
        ritual=post.get("ritual") == "1",
        free=free,
    )
    # Natural Recovery's free cast is one for all the Circle spells: the others lose theirs too.
    redraw = free and character.spells.filter(spell=spell, source__startswith="subclass:").exists()
    return {"message": _("Cast %(name)s") % {"name": spell.name}, "refresh": redraw}


def _act_xp(character, post):
    play.set_experience(character, _int(post, "value"))
    return True  # the progress bar under it moves


#: action name -> function(character, POST) -> True if the page must be redrawn afterwards
#: (something derived - AC, attacks - changed, which the script cannot recompute itself).
_ACTIONS = {
    "name": lambda c, p: play.rename(c, p.get("value", "")),
    "xp": _act_xp,
    "hp_delta": lambda c, p: play.adjust_hit_points(c, _int(p, "delta")),
    "hp_set": lambda c, p: play.set_hit_points(c, _int(p, "value")),
    # The sheet is redrawn: the lowered numbers show on the abilities, saves, skills and so on.
    "hp_max_reduction": lambda c, p: play.set_hit_point_reduction(c, _int(p, "value")) or True,
    "ability_reduction": lambda c, p: (
        play.set_ability_reduction(c, p.get("ability", ""), _int(p, "value")) or True
    ),
    "temp_hp": lambda c, p: play.set_temporary_hit_points(c, _int(p, "value")),
    "death_toggle": lambda c, p: play.toggle_death_save(c, p.get("kind", ""), _int(p, "index")),
    "inspiration": lambda c, p: play.set_inspiration(c, p.get("value") == "1"),
    "hit_dice": _act_hit_dice,
    "slots": _act_slots,
    "coin": lambda c, p: play.set_coin(c, p.get("coin", ""), _int(p, "value")),
    "text": lambda c, p: _act_text(c, p),
}


def _act_text(character, post):
    field, value = post.get("field", ""), post.get("value", "")
    changed = field in play.TEXT_FIELDS and getattr(character, field) != value
    if field == "backstory" and value == shown_backstory(character)[0]:
        return  # the textarea shows the machine translation: untouched, so the original stays
    play.set_text(character, field, value)
    if changed and field == "backstory":
        translations.enqueue("backstory", character.pk, {"backstory": character.backstory})


def _act_spell_add(character, post):
    limits = _prepared_limits(derived_stats.compute(character))
    spell = play.add_spell(character, post.get("spell", ""), limits).spell
    return {"refresh": True, "message": _("Added %(name)s") % {"name": spell.name}}


def _act_spell_prepare(character, post):
    spell_id = post.get("spell", "")
    stats = derived_stats.compute(character)
    row = character.spells.filter(spell_id=spell_id).first()
    class_id = row.klass_id if row else post.get("klass", "")
    entry = next((e for e in stats.spellcasting if e["source"] == f"class:{class_id}"), None)
    with transaction.atomic():
        if row is None:  # a class-list spell the spellbook offered without a row of its own
            if entry is None:
                raise ValueError("not a spell of one of this character's classes")
            play.learn_class_spell(character, spell_id, class_id, _max_spell_level(entry))
        limit = entry["prepared"] if entry else None
        play.set_spell_prepared(character, spell_id, post.get("prepared") == "1", limit=limit)
    return {"refresh": True}


def _act_spell_remove(character, post):
    play.remove_spell(character, post.get("spell", ""))
    return True


def _pick_values(data) -> dict[str, list[str]]:
    """The choices posted/queried as `pick.<key>=a,b` (see the feat dialog) as `{key: [a, b]}`."""
    return {
        key.removeprefix("pick."): [v for v in value.split(",") if v]
        for key, value in data.items()
        if key.startswith("pick.")
    }


def _act_feature_add(character, post):
    kind, _sep, ref = post.get("feature", "").partition(":")
    if kind == "feat":
        # A feat brings its grants and asks for its choices (Magic Initiate's spells...).
        feat = Feat.objects.get(pk=ref)
        progression.add_feat_from_sheet(character, feat, _pick_values(post))
        return {"refresh": True, "message": _("Added %(name)s") % {"name": feat.name}}
    entry = play.add_feature(character, kind, ref)
    return {"refresh": True, "message": _("Added %(name)s") % {"name": entry.name}}


def _act_feature_remove(character, post):
    kind, _sep, ref = post.get("feature", "").partition(":")
    play.remove_feature(character, kind, ref)
    return True


def _act_equip(character, post):
    play.set_equipped(character, _int(post, "item"), post.get("value") == "1")
    return True


def _number(post, name: str) -> float | None:
    """A decimal from a form field (`,` or `.`), `None` when it is left empty."""
    raw = post.get(name, "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} is not a number") from None


def _act_item_add(character, post):
    quantity = int(_number(post, "quantity") or 1)
    item = play.add_item(character, post.get("equipment", ""), quantity)
    return {"refresh": True, "message": _("Added %(name)s") % {"name": item.equipment.name}}


def _act_item_buy(character, post):
    quantity = int(_number(post, "quantity") or 1)
    item, price = play.buy_item(character, post.get("equipment", ""), quantity)
    return {
        "refresh": True,
        "message": _("Bought %(name)s for %(price)s")
        % {"name": item.equipment.name, "price": _gold_label(price)},
    }


def _act_custom_add(character, post):
    weight = _number(post, "weight")
    if weight is not None and units.is_metric():  # typed in kilograms, stored in pounds
        weight /= units.POUNDS_TO_KG
    cost = _number(post, "cost")  # in gold pieces
    bought = post.get("buy") == "1"  # paid for out of the purse, rather than just added
    item = play.add_custom_item(
        character,
        name=post.get("name", ""),
        section=post.get("section", "misc"),
        type_label=post.get("type", ""),
        weapon_category=post.get("weapon_category", ""),
        quantity=int(_number(post, "quantity") or 1),
        weight=weight,
        value=round(cost * 100) if cost is not None else None,
        valuable=post.get("valuable") == "1",
        description=post.get("description", ""),
        buy=bought,
    )
    if bought:
        message = _("Bought %(name)s for %(price)s") % {
            "name": item.name,
            "price": _gold_label(item.value * item.quantity),
        }
    else:
        message = _("Added %(name)s") % {"name": item.name}
    return {"refresh": True, "message": message}


def _act_item_qty(character, post):
    kind, item = post.get("kind", ""), _int(post, "item")
    if "delta" in post:
        play.adjust_item_quantity(character, kind, item, _int(post, "delta"))
    else:
        play.set_item_quantity(character, kind, item, _int(post, "value"))
    return True


def _act_item_remove(character, post):
    play.remove_item(character, post.get("kind", ""), _int(post, "item"))
    return True


def _act_item_sell(character, post):
    price = play.sell_item(
        character, post.get("kind", ""), _int(post, "item"), _int(post, "quantity")
    )
    return {"refresh": True, "message": _("Sold for %(price)s") % {"price": _gold_label(price)}}


_ACTIONS["equip"] = _act_equip
_ACTIONS["item_add"] = _act_item_add
_ACTIONS["item_buy"] = _act_item_buy
_ACTIONS["custom_add"] = _act_custom_add
_ACTIONS["item_qty"] = _act_item_qty
_ACTIONS["item_remove"] = _act_item_remove
_ACTIONS["item_sell"] = _act_item_sell
_ACTIONS["cast"] = _act_cast
_ACTIONS["short_rest"] = _act_short_rest
_ACTIONS["long_rest"] = _act_long_rest
_ACTIONS["weapon_mastery_swap"] = _act_mastery_swap
_ACTIONS["land_change"] = _act_land_change
_ACTIONS["resource"] = _act_resource
_ACTIONS["spell_add"] = _act_spell_add
_ACTIONS["spell_prepare"] = _act_spell_prepare
_ACTIONS["spell_remove"] = _act_spell_remove
_ACTIONS["feature_add"] = _act_feature_add
_ACTIONS["feature_remove"] = _act_feature_remove


def _state(character: Character) -> dict:
    """What the script redraws after an action."""
    stats = derived_stats.compute(character)
    classes = list(character.classes.select_related("klass"))
    purse = getattr(character, "currency", None)
    return {
        "name": character.name,
        "xp": character.experience_points,
        "hp": character.current_hit_points,
        "max_hp": character.hit_point_maximum,
        "con_modifier": stats.abilities["con"]["modifier"],
        "temp_hp": character.temporary_hit_points,
        "death_successes": character.death_save_successes,
        "death_failures": character.death_save_failures,
        "inspiration": character.inspiration,
        "hit_dice": {
            die: {"total": hd["total"], "spent": hd["spent"]} for die, hd in stats.hit_dice.items()
        },
        "slots": {
            p["key"]: {"max": p["max"], "spent": p["spent"]}
            for p in _slots(character, stats, classes)
        },
        "coins": {coin: getattr(purse, coin, 0) if purse else 0 for coin in play.COINS},
        "resources": {
            str(r.pk): {"current": r.current_uses, "max": r.max_uses}
            for r in character.resources.all()
        },
    }


@require_POST
def character_act(request, pk):
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        return JsonResponse({"error": "forbidden"}, status=403)
    action = request.POST.get("action", "")
    # Hit Dice and spell slots are only ever moved by hand by the DM or an admin; a player spends
    # them by casting / resting.
    if action in ("hit_dice", "slots") and not access.can_speak_as_dm(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    handler = _ACTIONS.get(action)
    if handler is None:
        return JsonResponse({"error": "unknown action"}, status=400)
    try:
        result = handler(character, request.POST)
    except (ValueError, ObjectDoesNotExist) as error:
        return JsonResponse({"error": str(error)}, status=400)
    # A handler answers True/None, or {"refresh": ..., "message": ...} with a note for the player.
    outcome = result if isinstance(result, dict) else {"refresh": bool(result)}
    character.refresh_from_db()
    response = JsonResponse(
        {
            "ok": True,
            "refresh": bool(outcome.get("refresh")),
            "message": outcome.get("message", ""),
            "prompt": outcome.get("prompt", ""),
            "prompt_tab": outcome.get("prompt_tab", ""),
            "state": _state(character),
        }
    )
    add_never_cache_headers(response)
    return response


@require_GET
def character_spells(request, pk):
    """The "add a spell" sheet: every spell as a filterable list, with the World's own filters. A
    fragment the sheet's script loads into its overlay the first time it is opened."""
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        return HttpResponse(status=403)
    known = set(character.spells.values_list("spell_id", flat=True))
    rows = [
        _spell_row(spell)
        for spell in Spell.objects.prefetch_related("saving_throw_abilities").order_by(
            "level", "name"
        )
    ]
    for row in rows:
        row["known"] = row["id"] in known
    return render(
        request,
        "frontend/characters/sheet/_add_spell.html",
        {"spells": rows, "filters": _spell_filters(rows)},
    )


def _feature_catalog_row(base: dict, ref: str, describe: str, known: set[str], **groups) -> dict:
    """One entry of the "add a feature" sheet, from one of the Features tab's own row builders
    (`_feature_row()` and friends): what the sheet's list shows, filters on and posts back."""
    return {
        "ref": ref,
        "name": base["name"],
        "search": base["search"],
        "detail": " · ".join(base["properties"]),
        "image": base["image"],
        "describe": describe,
        "type": base["type"],
        "known": ref in known,
        "klass": groups.get("klass", ""),
        "species": groups.get("species", ""),
    }


def _feature_catalog(character: Character) -> list[dict]:
    """Every feature, feat and option the character could be given, as rows of the "add a
    feature" sheet - the same catalog as the World's Features list (minus the Ability Score
    Improvement every class repeats), plus the options that have a page of their own."""
    known = {f"feature:{pk}" for pk in character.features.values_list("feature_id", flat=True)}
    known |= {f"feat:{pk}" for pk in character.feats.values_list("feat_id", flat=True)}
    known |= {
        f"option:{pk}"
        for pk in character.optional_features.values_list("optional_feature_id", flat=True)
    }
    rows = []
    features = (
        Feature.objects.filter(
            Q(class_level__isnull=False)
            | Q(subclass_level__isnull=False)
            | Q(species__isnull=False)
        )
        .exclude(name_en="Ability Score Improvement")
        .select_related("class_level__klass", "subclass_level__subclass__klass", "species")
    )
    for f in features:
        base = _feature_row(f)
        groups = (
            {"species": base["group"]} if base["type"] == "species" else {"klass": base["group"]}
        )
        rows.append(
            _feature_catalog_row(
                base, f"feature:{f.pk}", _describe_url("feature", f.pk), known, **groups
            )
        )
    for feat in Feat.objects.all():
        row = _feature_catalog_row(
            _feat_row(feat), f"feat:{feat.pk}", _describe_url("feat", feat.pk), known
        )
        # A feat with choices (Magic Initiate's spells...) asks for them in a dialog first.
        if progression.sheet_feat_pickers(character, feat, {}):
            row["picks_url"] = reverse("character-feature-picks", args=[character.pk])
        rows.append(row)
    for option in OptionalFeature.objects.all():
        rows.append(
            _feature_catalog_row(
                _option_row(option),
                f"option:{option.pk}",
                _describe_url("invocation", option.pk),
                known,
                klass=_option_class_id(option) or "",
            )
        )
    rows.sort(key=lambda row: row["name"].casefold())
    return rows


@require_GET
def character_feature_picks(request, pk):
    """The choices a feat asks for when it is added (`?feature=feat:<id>`, the ones made so far as
    `pick.<key>=a,b`): a fragment for the sheet's dialog, re-read when a choice decides what the
    others offer (Magic Initiate's spell list)."""
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        return HttpResponse(status=403)
    kind, _sep, ref = request.GET.get("feature", "").partition(":")
    feat = get_object_or_404(Feat, pk=ref) if kind == "feat" else None
    if feat is None:
        raise Http404
    pickers = progression.sheet_feat_pickers(character, feat, _pick_values(request.GET))
    for picker in pickers:
        picker.name = f"pick.{picker.key}"
    return render(
        request,
        "frontend/characters/sheet/_feat_picks.html",
        {"feat": feat, "pickers": pickers, "feature": request.GET.get("feature", "")},
    )


@require_GET
def character_features(request, pk):
    """The "add a feature" sheet: every feature, feat and option as a filterable list. A fragment
    the sheet's script loads into its overlay the first time it is opened."""
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        return HttpResponse(status=403)
    rows = _feature_catalog(character)
    filters = [_feature_type_filter(rows, always=True)]
    filters += [
        {
            "kind": "checkbox",
            "name": "class",
            "label": _("Class"),
            "values": set(),
            "options": [(c.pk, c.name) for c in Class.objects.order_by("name")],
            # Shown once the Type pill is one whose rows belong to a class.
            "only": "class subclass option",
        },
        {
            "kind": "checkbox",
            "name": "species",
            "label": _("Species"),
            "values": set(),
            "options": [(sp.pk, sp.name) for sp in Species.objects.order_by("name")],
            "only": "species",
        },
    ]
    return render(
        request,
        "frontend/characters/sheet/_add_feature.html",
        {"features": rows, "filters": filters},
    )


def inventory_filters(request=None, used_types: dict | None = None) -> list[dict]:
    """The item filters shared by the character's "add an item" sheet and the World > Items list.

    The main type comes first, as a row of pills (`section`). The other filters only appear once
    one is picked (`only`), and only the ones that mean something for it: a Mastery filter is no
    use among the armor. Each section has its own Type filter, listing just its types. With a
    `request` the current selection is read from its query string (the World list filters
    server-side); without, nothing is selected (the sheet filters client-side).
    """
    if used_types is None:
        section_of = {t: key for key, _label, types in _INVENTORY_SECTIONS for t in types}
        used_types = {
            (t or ""): section_of.get(t, "misc")
            for t in Equipment.objects.values_list("type_id", flat=True).distinct()
        }
    type_names = {t.pk: t.name for t in EquipmentType.objects.order_by("name")}

    def picked(name: str) -> set:
        return {v for v in request.GET.getlist(name) if v} if request else set()

    filters = [
        {
            "kind": "radio",
            "name": "section",
            "label": _("Type"),
            "all_label": _("All"),
            "value": request.GET.get("section", "").strip() if request else "",
            "options": [(key, label) for key, label, _types in _INVENTORY_SECTIONS],
        }
    ]

    def checkbox(name: str, label: str, options, only: str) -> dict:
        return {
            "kind": "checkbox",
            "name": name,
            "label": label,
            "values": picked(name),
            "options": options,
            "only": only,
        }

    for key, _label, _types in _INVENTORY_SECTIONS:
        filters.append(
            checkbox(
                "type",
                _("Type"),
                [
                    (pk, type_names[pk])
                    for pk in sorted(type_names, key=type_names.get)
                    if used_types.get(pk) == key
                ],
                key,
            )
        )
        if key == "weapons":
            filters += [
                checkbox(
                    "category",
                    _("Category"),
                    [
                        (c, _pick_translation(_WEAPON_CATEGORY_LABELS, c))
                        for c in ("simple", "martial")
                    ],
                    key,
                ),
                checkbox(
                    "property",
                    _("Properties"),
                    [
                        (p.pk, p.name)
                        for p in EquipmentProperty.objects.filter(hidden=False).order_by("name")
                    ],
                    key,
                ),
                checkbox(
                    "mastery",
                    _("Mastery"),
                    [(m.pk, m.name) for m in Mastery.objects.order_by("name")],
                    key,
                ),
            ]
    return filters


@require_GET
def character_items(request, pk):
    """The "add an item" sheet: every catalog item as a filterable list, plus the custom-item form.
    A fragment the sheet's script loads into its overlay the first time it is opened."""
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        return HttpResponse(status=403)
    catalog = Equipment.objects.select_related("type").prefetch_related("properties", "masteries")
    section_of = {t: key for key, _label, types in _INVENTORY_SECTIONS for t in types}
    rows = [
        {
            "id": e.pk,
            "name": e.name,
            "search": f"{e.name_en} {e.name_it}".lower(),
            "detail": _card_line("equipment", e),
            "url": reverse("character-catalog-item", args=[character.pk, e.pk]),
            "section": section_of.get(e.type_id, "misc"),
            "type": e.type_id or "",
            "category": e.weapon_category,
            "property": " ".join(p.pk for p in e.properties.all()),
            "mastery": " ".join(m.pk for m in e.masteries.all()),
            # In copper; the "Buy" button pays this out of the purse instead of adding it for free.
            "cost": e.value or 0,
        }
        for e in catalog
    ]
    used_types = {r["type"]: r["section"] for r in rows}
    type_names = {t.pk: t.name for t in EquipmentType.objects.order_by("name")}
    filters = inventory_filters(used_types=used_types)
    return render(
        request,
        "frontend/characters/sheet/_add_item.html",
        {
            "items": rows,
            "filters": filters,
            "sections": [(key, label) for key, label, _types in _INVENTORY_SECTIONS],
            # Suggestions for the custom item's free-text Type field - the catalog's own type
            # names, so a homebrew item can be labelled "Light Armor" or "Potion" like a real one.
            # One list per section - `character_sheet.js` swaps in the right one as the player
            # picks a Category, so a weapon doesn't get offered "Shield" as a type.
            "custom_types_by_section": {
                key: sorted({type_names[pk] for pk in type_names if used_types.get(pk) == key})
                for key, _label, _types in _INVENTORY_SECTIONS
            },
            # Only shown once Category is "weapons" (`character_sheet.js`).
            "weapon_categories": [
                (c, _pick_translation(_WEAPON_CATEGORY_LABELS, c)) for c in ("simple", "martial")
            ],
            "weight_unit": "kg" if units.is_metric() else "lb",
            "coins": _coins(character),
        },
    )


#: What each kind of item page lets the player do (see `character_item()`).
_ITEM_PAGE_ACTIONS = {
    "stack": ("equip", "item_qty", "item_sell", "item_remove"),
    "custom": ("item_qty", "item_sell", "item_remove"),
    "catalog": ("item_add", "item_buy"),
}


def _item_page_facts(kind: str, row) -> tuple[list, list]:
    """The facts and description sections of an item's page: a catalog item's own (the World's
    rendering, same as the old unfolding panel had), or what a custom item's owner wrote."""
    if kind != "custom":
        equipment = row if kind == "catalog" else row.equipment
        return _DESCRIBERS["equipment"](equipment.pk)
    labels = {key: label for key, label, _types in _INVENTORY_SECTIONS}
    facts = [(_("Category"), labels[row.section])]
    if row.type_label:
        facts.append((_("Type"), row.type_label))
    if row.weapon_category:
        facts.append(
            (_("Weapon category"), _pick_translation(_WEAPON_CATEGORY_LABELS, row.weapon_category))
        )
    if row.value:
        facts.append((_("Cost"), _gold_label(row.value)))
    if row.weight:
        facts.append((_("Weight"), _weight_text(row.weight)))
    return facts, []


def character_item(request, pk, kind, ref):
    """One item's page - the "description in a new view" of an inventory row or of a row of the
    "add an item" list, like a feature's page. Above the description, the editor's tools: quantity,
    equip, sell and remove for an item the character has; Add and Buy for a catalog one. They are
    plain forms posting back here (each runs the very action the sheet's script would), so no
    script is needed - the page just reloads, or goes back to the inventory once the item is
    gone."""
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_view(
        request.user, character
    ):
        raise Http404
    can_edit = access.can_edit(request.user, character)
    inventory_url = f"{reverse('character-detail', args=[pk])}?tab=inventory"
    if kind == "stack":
        row = get_object_or_404(
            character.inventory_items.select_related("equipment__type", "parent__equipment"),
            pk=ref,
        )
    elif kind == "custom":
        row = get_object_or_404(character.custom_items, pk=ref)
    else:
        row = get_object_or_404(Equipment.objects.select_related("type"), pk=ref)

    if request.method == "POST":
        action = request.POST.get("action", "")
        if not can_edit:
            return HttpResponse(status=403)
        if action not in _ITEM_PAGE_ACTIONS[kind]:
            return HttpResponse(status=400)
        post = request.POST.copy()
        # Which item is the page's own business, never the form's.
        if kind == "catalog":
            post["equipment"] = row.pk
        else:
            post["kind"] = "catalog" if kind == "stack" else "custom"
            post["item"] = row.pk
        try:
            result = _ACTIONS[action](character, post)
        except (ValueError, ObjectDoesNotExist):
            messages.error(request, _("Could not save that change."))
            return redirect(request.path)
        if kind != "catalog" and not type(row).objects.filter(pk=row.pk).exists():
            return redirect(inventory_url)  # sold or removed: nothing left to look at
        if isinstance(result, dict) and result.get("message"):
            messages.success(request, result["message"])
        return redirect(request.path)

    facts, sections = _item_page_facts(kind, row)
    if kind == "catalog":
        card = None
        name = row.name
        back_url = f"{inventory_url}&overlay=item"
    else:
        card = _item_card("custom" if kind == "custom" else "catalog", row)
        name = card["name"]
        back_url = inventory_url
        if not can_edit:  # an editor has the quantity right there, in the tools
            facts = [*facts, (_("Quantity"), row.quantity)]
    cost = row.value if kind == "catalog" else 0
    purse = play.purse_copper(character) if kind == "catalog" else 0
    tools = render_to_string(
        "frontend/characters/_item_tools.html",
        {
            "kind": kind,
            "can_edit": can_edit,
            "card": card,
            "equipment": row if kind == "catalog" else None,
            "description": row.description if kind == "custom" else "",
            "sections": sections,
            "cost": _gold_label(cost) if cost else "",
            "can_afford": bool(cost) and cost <= purse,
            "left": _gold_label(max(0, purse - cost)) if cost else "",
            "messages": messages.get_messages(request),
        },
        request=request,
    )
    response = render(
        request,
        "frontend/characters/item.html",
        {
            "page_title": name,
            "back_url": back_url,
            "facts": facts,
            "body": mark_safe(tools.strip()),  # noqa: S308 - rendered from our own template
        },
    )
    add_never_cache_headers(response)
    return response


def _frame_of(post) -> tuple[str, str, str]:
    return post.get("cx", "0.5"), post.get("cy", "0.5"), post.get("zoom", "1")


def character_avatar(request, pk):
    """The round avatar: the portrait cut to the character's frame (the URL carries the frame,
    so a changed frame is never a cached old one)."""
    character = get_object_or_404(Character, pk=pk)
    if request.method != "GET":
        return HttpResponse(status=405)
    if not access.can_view(request.user, character) or not character.portrait:
        raise Http404
    try:
        data = portrait.avatar_bytes(character)
    except (FileNotFoundError, OSError):
        raise Http404 from None
    response = HttpResponse(data, content_type="image/webp")
    response["Cache-Control"] = "private, max-age=86400"
    return response


def character_portrait(request, pk):
    """The character's picture. GET serves it to whoever may see the character; POST (the owner
    only) uploads a new one from the `file` field, or removes it with `remove=1`."""
    character = get_object_or_404(Character, pk=pk)
    if request.method == "POST":
        if character.status != Character.STATUS_COMPLETE or not access.can_edit(
            request.user, character
        ):
            return JsonResponse({"error": "forbidden"}, status=403)
        try:
            if request.POST.get("remove"):
                portrait.clear_portrait(character)
            elif request.FILES.get("file"):
                portrait.set_portrait(character, request.FILES["file"], _frame_of(request.POST))
            elif character.portrait and "zoom" in request.POST:
                portrait.set_frame(character, *_frame_of(request.POST))
            else:
                raise ValueError(_("Choose a picture."))
        except ValueError as error:
            return JsonResponse({"error": str(error)}, status=400)
        response = JsonResponse({"ok": True, "refresh": True})
        add_never_cache_headers(response)
        return response
    if request.method != "GET":
        return HttpResponse(status=405)
    if not access.can_view(request.user, character) or not character.portrait:
        raise Http404
    try:
        with character.portrait.open("rb") as file:
            data = file.read()  # a few tens of KB: no need to stream it (ASGI warns about that)
    except FileNotFoundError:
        raise Http404 from None
    response = HttpResponse(data, content_type="image/webp")
    # The URL carries the file's name (`?v=`), which changes with every upload.
    response["Cache-Control"] = "private, max-age=86400"
    return response


def character_picture(request, pk, picture_id=None):
    """The character's gallery. POST (the owner only) adds the `file` field, or deletes the
    picture in `remove`; GET serves one picture to whoever may see the character."""
    character = get_object_or_404(Character, pk=pk)
    if request.method == "POST":
        if character.status != Character.STATUS_COMPLETE or not access.can_edit(
            request.user, character
        ):
            return JsonResponse({"error": "forbidden"}, status=403)
        try:
            if request.POST.get("remove", "").isdigit():
                portrait.remove_picture(character, int(request.POST["remove"]))
            elif request.FILES.get("file"):
                portrait.add_picture(character, request.FILES["file"])
            else:
                raise ValueError(_("Choose a picture."))
        except ValueError as error:
            return JsonResponse({"error": str(error)}, status=400)
        response = JsonResponse({"ok": True, "refresh": True})
        add_never_cache_headers(response)
        return response
    if request.method != "GET" or picture_id is None:
        return HttpResponse(status=405)
    picture = get_object_or_404(character.pictures, pk=picture_id)
    if not access.can_view(request.user, character):
        raise Http404
    try:
        with picture.image.open("rb") as file:
            data = file.read()
    except FileNotFoundError:
        raise Http404 from None
    response = HttpResponse(data, content_type="image/webp")
    response["Cache-Control"] = "private, max-age=86400"
    return response
