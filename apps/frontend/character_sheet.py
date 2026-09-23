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

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, pgettext_lazy
from django.views.decorators.http import require_GET, require_POST

from apps.builder import tables
from apps.builder.resolvers.proficiency import WeaponProficiency
from apps.builder.services import creation, derived_stats
from apps.characters.models import Character, CharacterChoice
from apps.characters.services import access, play, portrait
from apps.frontend import units
from apps.frontend.character_views import (
    _card_line,
    _damage_text,
    _gold_label,
    _step_url,
    _warning_text,
)
from apps.frontend.views import (
    _CASTING_TIME_FILTER_LABELS,
    _SCHOOL_LABELS,
    _SIZE_LABELS,
    _WEAPON_CATEGORY_LABELS,
    _class_name,
    _format_feat_category,
    _menu_image_url,
    _pick_translation,
)
from apps.rules.models import (
    Ability,
    ClassLevel,
    Equipment,
    EquipmentProperty,
    EquipmentType,
    Mastery,
    Skill,
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
    ("copper", gettext_lazy("Copper"), "CP"),
    ("silver", gettext_lazy("Silver"), "SP"),
    ("gold", gettext_lazy("Gold"), "GP"),
    ("platinum", gettext_lazy("Platinum"), "PP"),
)
_ELECTRUM = ("electrum", gettext_lazy("Electrum"), "EP")
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
    }


def _percent(part: int, whole: int) -> int:
    return round(max(0, min(1, part / whole)) * 100) if whole else 0


def _strip(character: Character, stats, items) -> dict:
    shield = next((i for i in items if i.equipment.type_id == play.SHIELD_TYPE), None)
    return {
        "armor_class": stats.armor_class["value"],
        "shield_item": shield.pk if shield else None,
        "shield_worn": stats.armor_class["shield"],
        "initiative": stats.initiative,
        "hp": character.current_hit_points,
        "max_hp": character.max_hit_points,
        "hp_percent": _percent(character.current_hit_points, character.max_hit_points),
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


def _features(character: Character) -> list[dict]:
    """Groups of `{name, detail, describe}` rows: species traits, each class's features, each
    subclass's, then the feats and options (invocations, maneuvers, ...) the player picked."""
    granted = [
        cf.feature
        for cf in character.features.select_related(
            "feature__class_level__klass", "feature__subclass_level__subclass", "feature__species"
        )
    ]
    groups: dict[tuple, dict] = {}

    def add(order, title, subtitle, name, detail, kind, pk, level=0):
        group = groups.setdefault(
            (order, title, subtitle), {"title": title, "subtitle": subtitle, "rows": []}
        )
        group["rows"].append(
            {
                "name": name,
                "detail": detail,
                "describe": _describe_url(kind, pk),
                "level": level,
                "pk": pk,
            }
        )

    for f in granted:
        if f.species_id:
            add(0, _("Species Traits"), f.species.name, f.name, "", "feature", f.pk)
        elif f.class_level_id:
            level = f.class_level.level
            add(
                1,
                _("Class Features"),
                f.class_level.klass.name,
                f.name,
                f"{_('Level')} {level}",
                "feature",
                f.pk,
                level,
            )
        elif f.subclass_level_id:
            level = f.subclass_level.level
            add(
                2,
                _("Subclass Features"),
                f.subclass_level.subclass.name,
                f.name,
                f"{_('Level')} {level}",
                "feature",
                f.pk,
                level,
            )
    for cf in character.feats.select_related("feat"):
        source = cf.source.split(":")[0] if cf.source else ""
        detail = " · ".join(
            x for x in (_format_feat_category(cf.feat.category), source.capitalize()) if x
        )
        add(3, _("Feats"), "", cf.feat.name, detail, "feat", cf.feat_id)
    for co in character.optional_features.select_related("optional_feature"):
        add(
            4,
            _("Options"),
            "",
            co.optional_feature.name,
            co.optional_feature.feature_type,
            "invocation",
            co.optional_feature_id,
        )

    result = []
    for _key, group in sorted(groups.items(), key=lambda kv: kv[0][:1] + (kv[0][2],)):
        group["rows"].sort(key=lambda r: (r["level"], r["pk"]))
        result.append(group)
    return result


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
    """Every slot pool with its pips: `[{key, label, max, spent, pips}]`."""
    maximums, pact = _slot_maximums(stats, classes)
    spent = character.spell_slots_spent
    pools = [
        {"key": str(level), "label": f"{_('Level')} {level}", "max": count}
        for level, count in enumerate(maximums, start=1)
        if count
    ]
    if pact:
        pools.append(
            {
                "key": "pact",
                "label": _("Pact Magic (level %(level)s)") % {"level": pact["level"]},
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
                "ability": ability_names.get(entry["ability"], entry["ability"]),
                "origin": origin,
                "modifier": stats.abilities[entry["ability"]]["modifier"],
                "dc": entry["save_dc"],
                "attack": entry["attack_bonus"],
            }
        )
    return sources


def _spell_row(spell, status: str = "") -> dict:
    """One spell as a list row - in the spellbook, and in the "add a spell" sheet, which filters
    the same way: `level`/`school`/... are what the filter buttons compare against."""
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


def _spell_rows(character: Character) -> list[dict]:
    rows = []
    for cs in (
        character.spells.select_related("spell", "klass")
        .prefetch_related("spell__saving_throw_abilities")
        .order_by("spell__level", "spell__name")
    ):
        if cs.always_prepared:
            status = _("Always prepared")
        elif cs.prepared and cs.spell.level > 0:
            status = _("Prepared")
        elif cs.in_spellbook:
            status = _("In spellbook")
        else:
            status = ""
        row = _spell_row(cs.spell, status)
        # A spell the player added by hand can be taken away again; the ones a class, species or
        # feat gave cannot.
        row["removable"] = cs.source == play.SPELL_SOURCE
        rows.append(row)
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


def _spellbook(character: Character, stats, classes) -> dict:
    rows = _spell_rows(character)
    return {
        "sources": _casting_sources(stats, classes),
        "slots": _slots(character, stats, classes),
        "spells": rows,
        "spell_filters": _spell_filters(rows),
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
        # A catalog item unfolds to its catalog description; a custom one to what the player wrote.
        "describe": "" if custom else _describe_url("equipment", eq.pk),
        "description": row.description if custom else "",
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
        "warning_texts": [_warning_text(w) for w in stats.warnings],
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


def _biography(character: Character) -> dict:
    return {
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
    tab = request.GET.get("tab", "")
    response = render(
        request,
        "frontend/characters/detail.html",
        {
            "page_title": character.name,
            "back_url": reverse("characters-overview"),
            "character": character,
            "can_edit": access.can_edit(request.user, character),
            # Not `tabs`/`active_tab`: base.html draws its own `?tab=` strip for those names.
            "sheet_tabs": TABS,
            "sheet_tab": tab if tab in dict(TABS) else DEFAULT_TAB,
            "header": _header(character, stats),
            "strip": _strip(character, stats, items),
            "abilities": _abilities(stats),
            "feature_groups": _features(character),
            "spellbook": _spellbook(character, stats, classes),
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


def _act_slots(character, post):
    key = post.get("key", "")
    spent = int(character.spell_slots_spent.get(key, 0)) + _int(post, "delta")
    play.set_slots_spent(character, key, spent, _slot_maximum(character, key))


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
    "temp_hp": lambda c, p: play.set_temporary_hit_points(c, _int(p, "value")),
    "death_toggle": lambda c, p: play.toggle_death_save(c, p.get("kind", ""), _int(p, "index")),
    "inspiration": lambda c, p: play.set_inspiration(c, p.get("value") == "1"),
    "hit_dice": _act_hit_dice,
    "slots": _act_slots,
    "coin": lambda c, p: play.set_coin(c, p.get("coin", ""), _int(p, "value")),
    "text": lambda c, p: play.set_text(c, p.get("field", ""), p.get("value", "")),
}


def _act_spell_add(character, post):
    spell = play.add_spell(character, post.get("spell", "")).spell
    return {"refresh": True, "message": _("Added %(name)s") % {"name": spell.name}}


def _act_spell_remove(character, post):
    play.remove_spell(character, post.get("spell", ""))
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
    )
    return {"refresh": True, "message": _("Added %(name)s") % {"name": item.name}}


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
_ACTIONS["spell_add"] = _act_spell_add
_ACTIONS["spell_remove"] = _act_spell_remove


def _state(character: Character) -> dict:
    """What the script redraws after an action."""
    stats = derived_stats.compute(character)
    classes = list(character.classes.select_related("klass"))
    purse = getattr(character, "currency", None)
    return {
        "name": character.name,
        "xp": character.experience_points,
        "hp": character.current_hit_points,
        "max_hp": character.max_hit_points,
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
    }


@require_POST
def character_act(request, pk):
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        return JsonResponse({"error": "forbidden"}, status=403)
    handler = _ACTIONS.get(request.POST.get("action", ""))
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
            "describe": _describe_url("equipment", e.pk),
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
    # The main type comes first, as a row of pills. The other filters only appear once one is
    # picked (`only`), and only the ones that mean something for it: a Mastery filter is no use
    # among the armor. Each section has its own Type filter, listing just its types.
    used_types = {r["type"]: r["section"] for r in rows}
    type_names = {t.pk: t.name for t in EquipmentType.objects.order_by("name")}
    filters = [
        {
            "kind": "radio",
            "name": "section",
            "label": _("Type"),
            "all_label": _("All"),
            "value": "",
            "options": [(key, label) for key, label, _types in _INVENTORY_SECTIONS],
        }
    ]

    def checkbox(name: str, label: str, options, only: str) -> dict:
        return {
            "kind": "checkbox",
            "name": name,
            "label": label,
            "values": set(),
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
                portrait.set_portrait(character, request.FILES["file"])
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
