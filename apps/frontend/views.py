import unicodedata
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import login, logout
from django.db.models import Prefetch, Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.html import escape, format_html, format_html_join
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.characters.services import access
from apps.frontend import accounts, cloudflare_access, units
from apps.frontend.bookmarks import BOOKMARK_MODELS, bookmarked_ids, is_bookmarked
from apps.frontend.entries_render import (
    homebrew_badge,
    render_class_features,
    render_entries,
    render_handbook_section,
    render_key_value_table,
    render_starting_equipment,
    render_subclasses,
    render_text,
    render_trait_cards,
    self_translated_badge,
)
from apps.frontend.forms import NameForm, SignInForm
from apps.frontend.handbook_search import find_hits, name_matches, query_pattern
from apps.frontend.models import Bookmark
from apps.rules.models import Ability, Class, Equipment, Feature, Subclass
from apps.rules.services import background as background_service
from apps.rules.services import class_ as class_service
from apps.rules.services import equipment as equipment_service
from apps.rules.services import feat as feat_service
from apps.rules.services import feature as feature_service
from apps.rules.services import handbook as handbook_service
from apps.rules.services import optional_feature as optional_feature_service
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

# Small closed vocabularies that label raw source *codes* (not free text) on the About-tab facts
# - a size letter, a creature-type word, an armor/weapon proficiency category, a tool-choice
# placeholder. These aren't `gettext()` calls: several of the plain English words involved
# ("All", "Light", "Simple", ...) are common enough that reusing the shared `.po` catalog for them
# risks colliding with an unrelated, differently-cased UI string that happens to need the same
# English spelling (confirmed for "All" - the existing generic "show everything" filter pill
# translates it as "Tutti", not the "Tutte" a weapon category needs) - so each gets its own
# (English, Italian) pair here instead, picked by `_pick_translation()` per request.
_SIZE_LABELS = {
    "T": ("Tiny", "Minuscola"),
    "S": ("Small", "Piccola"),
    "M": ("Medium", "Media"),
    "L": ("Large", "Grande"),
    "H": ("Huge", "Enorme"),
    "G": ("Gargantuan", "Mastodontica"),
}
# Only "humanoid" is verified to occur in `db/species.json` today (every current Species is one) -
# the rest of the D&D creature-type taxonomy is included so a future data refresh that adds e.g. a
# Giant or Fiend species doesn't silently show an untranslated code.
_CREATURE_TYPE_LABELS = {
    "aberration": ("Aberration", "Aberrazione"),
    "beast": ("Beast", "Bestia"),
    "celestial": ("Celestial", "Celestiale"),
    "construct": ("Construct", "Costrutto"),
    "dragon": ("Dragon", "Drago"),
    "elemental": ("Elemental", "Elementale"),
    "fey": ("Fey", "Folletto"),
    "fiend": ("Fiend", "Immondo"),
    "giant": ("Giant", "Gigante"),
    "humanoid": ("Humanoid", "Umanoide"),
    "monstrosity": ("Monstrosity", "Mostruosità"),
    "ooze": ("Ooze", "Melma"),
    "plant": ("Plant", "Pianta"),
    "undead": ("Undead", "Non Morto"),
}
_ARMOR_CATEGORY_LABELS = {
    "light": ("Light", "Leggera"),
    "medium": ("Medium", "Media"),
    "heavy": ("Heavy", "Pesante"),
    "shield": ("Shield", "Scudo"),
}
# Only "simple" and "all" are verified to occur in `db/classes.json` (Monk/Rogue; every other
# class's `weapon_proficiencies` is empty, so its fact row doesn't render at all) - "martial" is
# included for the same forward-compatibility reason as the creature types above. `Class`'s own
# docstring notes "all" here can carry a `fromFilter` restriction (e.g. Monk's is actually "martial
# weapons with the Light property", not literally every weapon) that this label doesn't unpack -
# unchanged from the English behavior, which shows the same bare "All".
_WEAPON_CATEGORY_LABELS = {
    "simple": ("Simple", "Semplici"),
    "martial": ("Martial", "Da Guerra"),
    "all": ("All", "Tutte"),
}
# `Class.tool_proficiencies`/`Background.tools`' own ad hoc "choose N of this category" shape
# (e.g. `{"anyMusicalInstrument": 3}`, see those models' docstrings) rendered its bare camelCase
# key verbatim before this - not translated wrong, just never turned into words in either
# language; these are the only three such keys currently in the data.
_TOOL_CHOICE_LABELS = {
    "anyMusicalInstrument": ("a musical instrument", "uno strumento musicale"),
    "anyArtisansTool": ("an artisan's tool", "uno strumento da artigiano"),
    "anyGamingSet": ("a gaming set", "un gioco"),
}
# `Feat.category` is decoded from the source's short code at import time (see the model's
# docstring) - a raw code, not `entries` prose, so it's translated the same way as the codes
# above rather than through the overlay pipeline. "Fighting Style (P)"/"(R)" sub-variants keep
# their parenthetical suffix as-is (a class-group marker, not English prose) - only the base
# category word is looked up, see `_format_feat_category()`.
_FEAT_CATEGORY_LABELS = {
    "Epic Boon": ("Epic Boon", "Dono epico"),
    "Fighting Style": ("Fighting Style", "Stile di combattimento"),
    "General": ("General", "Generale"),
    "Origin": ("Origin", "Origini"),
}


def _format_feat_category(category: str) -> str:
    base, _paren, suffix = category.partition(" (")
    label = _pick_translation(_FEAT_CATEGORY_LABELS, base)
    return f"{label} ({suffix}" if suffix else label


# `OptionalFeature` (Eldritch Invocation, Metamagic, Battle Master Maneuver) has no direct `Class`
# FK - see the model's docstring - but every current row is exactly one of these three, decoded
# from the source's own "EI"/"MM"/"MV:B" codes at import time (`OPTIONAL_FEATURE_TYPE_CODES` in
# the importer) into exactly the three `feature_type` strings below, verified against all 58 rows
# in db/optionalfeatures.json. Used both for an Option's icon (`features_classes/<id>.jpeg`, the
# same folder Class Features use) and for the "Class" fact on its own detail page.
_OPTION_CLASS_ID = {
    "Eldritch Invocation": "warlock",
    "Metamagic": "sorcerer",
    "Maneuver, Battle Master": "fighter",
}


def _option_class_id(option) -> str | None:
    return _OPTION_CLASS_ID.get(option.feature_type)


# `Spell.school`/`Spell.casting_time` are raw structured data (not `entries` prose), so they're
# never touched by the translation pipeline at all - these are the fixed vocabularies that need
# translating for display, same treatment as the other closed-vocabulary dicts above. Note the
# classic Italian D&D swap: English "Conjuration"/"Evocation" map to Italian "Evocazione"/
# "Invocazione" - the other way around from what the English cognates would suggest - confirmed
# against this project's own already-translated Evoker subclass ("Invocatore") and its Evocation-
# school features ("scuola di Invocazione").
_SCHOOL_LABELS = {
    "Abjuration": ("Abjuration", "Abiurazione"),
    "Conjuration": ("Conjuration", "Evocazione"),
    "Divination": ("Divination", "Divinazione"),
    "Enchantment": ("Enchantment", "Ammaliamento"),
    "Evocation": ("Evocation", "Invocazione"),
    "Illusion": ("Illusion", "Illusione"),
    "Necromancy": ("Necromancy", "Necromanzia"),
    "Transmutation": ("Transmutation", "Trasmutazione"),
}
_CASTING_TIME_UNIT_LABELS = {
    "action": ("action", "azione"),
    "bonus": ("bonus action", "azione bonus"),
    "reaction": ("reaction", "reazione"),
    "minute": ("minute", "minuto"),
    "hour": ("hour", "ora"),
}
# `rules.services.spell.list_casting_times()` bakes its own English display label per option
# (`_CASTING_TIME_LABELS` there) - translated here by exact match rather than reusing
# `_CASTING_TIME_UNIT_LABELS` above, since the filter's labels are already-pluralized whole
# phrases ("10 Minutes"), not a bare number + unit `_format_casting_time()` assembles itself.
_CASTING_TIME_FILTER_LABELS = {
    "1 Action": ("1 Action", "1 azione"),
    "1 Bonus Action": ("1 Bonus Action", "1 azione bonus"),
    "1 Reaction": ("1 Reaction", "1 reazione"),
    "1 Minute": ("1 Minute", "1 minuto"),
    "10 Minutes": ("10 Minutes", "10 minuti"),
    "1 Hour": ("1 Hour", "1 ora"),
    "8 Hours": ("8 Hours", "8 ore"),
    "12 Hours": ("12 Hours", "12 ore"),
    "24 Hours": ("24 Hours", "24 ore"),
}
# `Spell.casting_time`'s free-text `condition` (only on Reaction-cast spells, e.g. "which you take
# when you are hit by an attack roll...") is prose, but it's structured data outside `entries`, so
# it's translated here by exact match rather than through the overlay pipeline - there are only
# ever a handful of distinct sentences across the whole catalog (most Reaction spells share one).
_CASTING_TIME_CONDITIONS = {
    "which you take immediately after hitting a target with a Melee weapon or an "
    "{@variantrule Unarmed Strike|XPHB}": (
        "che compi subito dopo aver colpito un bersaglio con un'arma da mischia o con un "
        "{@variantrule Unarmed Strike|XPHB|colpo senz'armi}"
    ),
    "which you take immediately after hitting a creature with a Melee weapon or an "
    "{@variantrule Unarmed Strike|XPHB}": (
        "che compi subito dopo aver colpito una creatura con un'arma da mischia o con un "
        "{@variantrule Unarmed Strike|XPHB|colpo senz'armi}"
    ),
    "which you take immediately after hitting a creature with a weapon": (
        "che compi subito dopo aver colpito una creatura con un'arma"
    ),
    "which you take when you or a creature you can see within 60 feet of you falls": (
        "che compi quando tu o una creatura che riesci a vedere entro 18 metri da te cade"
    ),
    "which you take immediately after hitting a creature with a Ranged weapon": (
        "che compi subito dopo aver colpito una creatura con un'arma a distanza"
    ),
    "which you take in response to taking damage from a creature that you can see within 60 "
    "feet of yourself": (
        "che compi in risposta a subire danni da una creatura che riesci a vedere entro 18 metri "
        "da te"
    ),
    "which you take when you are hit by an attack roll or targeted by the Magic Missile spell": (
        "che compi quando sei colpito da un tiro per colpire o preso di mira dall'incantesimo "
        "{@spell Magic Missile|XPHB|dardo incantato}"
    ),
    "which you take when you see a creature within 60 feet of yourself casting a spell with "
    "Verbal, Somatic, or Material components": (
        "che compi quando vedi una creatura entro 18 metri da te lanciare un incantesimo con "
        "componenti Verbali, Somatiche o Materiali"
    ),
    "which you take immediately after hitting or missing a target with a ranged attack using a "
    "weapon": (
        "che compi subito dopo aver colpito o mancato un bersaglio con un attacco a distanza "
        "usando un'arma"
    ),
}


def _pick_translation(table: dict[str, tuple[str, str]], code: str) -> str:
    """The Italian half of `table[code]` on the Italian site, the English half otherwise, or
    `code` unchanged if it's not in `table` at all.
    """
    english, italian = table.get(code, (code, code))
    return italian if (get_language() or "en").startswith("it") else english


def _ability_names() -> dict[str, str]:
    """`{short code: full name}` for every `Ability` (e.g. "str" -> "Strength"/"Forza") - one
    query per call, reading `Ability.name` so it already follows the active language once
    `db/it/abilities.json` covers it (see `apps/rules/translation.py`), rather than a hardcoded
    English dict.
    """
    return dict(Ability.objects.values_list("pk", "name"))


def _classes_by_name() -> dict[str, Class]:
    """`{English class name: Class}` for every real `Class` row - one query per call, so
    `_format_spell_classes()` doesn't issue one per entry in `Spell.classes`.
    """
    return {c.name_en: c for c in Class.objects.all()}


def _class_name(english_name: str) -> str:
    """A `Spell.classes` entry's own (already-translated) `Class.name` - every entry matches a
    real `Class` row (see `spell_service.list_classes()`'s docstring). For the filter dropdown,
    which only needs the label, not a link.
    """
    return _classes_by_name()[english_name].name


def _format_spell_classes(class_names: list[str]) -> str:
    """`Spell.classes` (plain English names, see the model's docstring) as a comma-separated list
    of links to each class's own detail page.
    """
    classes_by_name = _classes_by_name()
    parts = [
        format_html(
            '<a href="{}">{}</a>',
            reverse("world-class-detail", args=[classes_by_name[name].pk]),
            classes_by_name[name].name,
        )
        for name in class_names
    ]
    return format_html_join(", ", "{}", ((part,) for part in parts))


def _proficiency_label(code: str) -> str:
    """One key from an armor/weapon proficiency flag grant: a category code (looked up in
    `_ARMOR_CATEGORY_LABELS`/`_WEAPON_CATEGORY_LABELS`) if it's one of those, else an `Equipment`
    row's own (already-translated) name if `code` matches one case-insensitively - covers
    `Class.tool_proficiencies`/`Background.tools`' named-tool keys (e.g. "thieves' tools"), which
    are just the source's own lowercase Equipment names - else `code.capitalize()` as before.
    """
    for table in (_ARMOR_CATEGORY_LABELS, _WEAPON_CATEGORY_LABELS):
        if code in table:
            return _pick_translation(table, code)
    equipment = Equipment.objects.filter(name_en__iexact=code).first()
    return equipment.name if equipment else code.capitalize()


def _format_ability_choice(raw_list):
    """`Background.ability_scores`: a list of alternative weighted spreads (see the model's
    docstring) - e.g. "Constitution +2, Intelligence +1 or Constitution +1, Intelligence +1,
    Wisdom +1".
    """
    ability_names = _ability_names()
    alternatives = []
    for alt in raw_list or []:
        weighted = ((alt.get("choose") or {}).get("weighted")) or {}
        names = [ability_names.get(c, c) for c in weighted.get("from", [])]
        weights = weighted.get("weights", [])
        pieces = [f"{n} +{w}" for n, w in zip(names, weights, strict=False)]
        if pieces:
            alternatives.append(", ".join(pieces))
    return f" {_('or')} ".join(alternatives)


def _format_feat_ability(raw_list):
    """`Feat.ability`: the feat's ability score increase - "Charisma +1" for a fixed one, "Strength
    or Dexterity +1" for a choice, with the cap the source gives (30 for Epic Boons, otherwise the
    usual 20). "" when the feat has none (entries flagged `hidden` are the source's own way of
    saying not to show it).
    """
    ability_names = _ability_names()
    parts = []
    for entry in raw_list or []:
        if entry.get("hidden"):
            continue
        choose = entry.get("choose")
        if choose:
            names = f" {_('or')} ".join(ability_names.get(c, c) for c in choose.get("from", []))
            if len(choose.get("from", [])) >= 6:
                names = _("One ability score of your choice")
            parts.append(f"{names} +{choose.get('amount', choose.get('count', 1))}")
            cap = entry.get("max", 20)
        else:
            parts.extend(f"{ability_names.get(c, c)} +{n}" for c, n in entry.items() if c != "max")
            cap = entry.get("max", 20)
    if not parts:
        return ""
    return f"{', '.join(parts)} ({_('maximum')} {cap})"


_WEAPON_PROPERTY_LABELS = {
    "light": ("Light", "Leggera"),
    "finesse": ("Finesse", "Accurata"),
}


def _format_weapon_filter(spec: str):
    """A filtered weapon grant (`{"all": {"fromFilter": "type=martial weapon|property=light"}}`,
    Monk/Rogue): "Martial weapons with the Light property"."""
    parts = dict(p.split("=", 1) for p in spec.split("|") if "=" in p)
    category = parts.get("type", "").removesuffix(" weapon")
    properties = [
        _pick_translation(_WEAPON_PROPERTY_LABELS, name).lower()
        for name in parts.get("property", "").split(";")
        if name
    ]
    text = (
        _pick_translation(_WEAPON_CATEGORY_LABELS, category)
        if category in _WEAPON_CATEGORY_LABELS
        else category.capitalize()
    )
    if not properties:
        return text
    return _("%(category)s weapons with the %(properties)s property") % {
        "category": text,
        "properties": f" {_('or')} ".join(properties),
    }


def _format_flag_grant(raw_list):
    """A flat/choice proficiency-grant list shared by `Class.armor_proficiencies`/
    `weapon_proficiencies`/`tool_proficiencies` and `Background.tools` - each entry is either a
    plain `{"name": true}` flag or an ad hoc placeholder+count/filter shape. Named flags come
    first as a comma-separated line; the "choose N of this category" entries follow as one
    bulleted list per count, under a "Choose N:" heading.
    """
    parts = []
    choices: dict[int, list[str]] = {}
    for entry in raw_list or []:
        for key, value in entry.items():
            if value is True:
                parts.append(_proficiency_label(key))
            elif isinstance(value, bool):
                continue
            elif isinstance(value, int):
                choices.setdefault(value, []).append(_pick_translation(_TOOL_CHOICE_LABELS, key))
            elif isinstance(value, dict):
                if isinstance(value.get("fromFilter"), str):
                    parts.append(_format_weapon_filter(value["fromFilter"]))
                else:
                    parts.append(_proficiency_label(key))
    html = format_html_join(", ", "{}", ((part,) for part in parts))
    for count, options in choices.items():
        items = format_html_join("", "<li>{}</li>", ((option,) for option in options))
        html += format_html("<div>{} {}:</div><ul>{}</ul>", _("Choose"), count, items)
    return html


def _format_prerequisite(raw_list):
    """`Feat.prerequisite`/`OptionalFeature.prerequisite`: a structured list of `{level, ability,
    feature, proficiency, otherSummary}` entries - see `Feat`'s docstring.
    """
    ability_names = _ability_names()
    alternatives = []
    for entry in raw_list or []:
        bits = []
        if "level" in entry:
            bits.append(f"{_('Level')} {entry['level']}")
        if "ability" in entry:
            bits.append(
                ", ".join(
                    f"{ability_names.get(code, code)} {score}+"
                    for a in entry["ability"]
                    for code, score in a.items()
                )
            )
        if "feature" in entry:
            bits.append(", ".join(entry["feature"]))
        if "proficiency" in entry:
            bits.append(
                ", ".join(
                    _proficiency_label(key)
                    for p in entry["proficiency"]
                    for key, val in p.items()
                    if val
                )
            )
        if "otherSummary" in entry:
            summary = entry["otherSummary"]
            bits.append(summary.get("entrySummary") or summary.get("entry", ""))
        alternatives.append(", ".join(b for b in bits if b))
    return f" {_('or')} ".join(a for a in alternatives if a)


def _format_size(codes: list[str] | None) -> str:
    return "/".join(_pick_translation(_SIZE_LABELS, c) for c in codes or [])


def _format_creature_types(codes: list[str] | None) -> str:
    return ", ".join(_pick_translation(_CREATURE_TYPE_LABELS, c) for c in codes or [])


def _format_casting_time(raw_list):
    parts = []
    for entry in raw_list or []:
        unit = _pick_translation(_CASTING_TIME_UNIT_LABELS, entry.get("unit", ""))
        text = f"{entry.get('number', '')} {unit}".strip()
        condition = entry.get("condition")
        if condition:
            # `_CASTING_TIME_CONDITIONS` is `{english: italian}`, not an `(english, italian)`
            # pair like `_pick_translation()`'s other tables - the English text is already
            # correct as-is, so there's nothing to look up on the English site.
            if (get_language() or "en").startswith("it"):
                condition = _CASTING_TIME_CONDITIONS.get(condition, condition)
            # `condition` carries `{@tag ...}` markup (e.g. "...or an
            # {@variantrule Unarmed Strike|XPHB}") that plain `escape()`/`{{ }}` would show
            # literally - `render_text()` resolves it the same way `entries` prose does.
            text = format_html("{}, {}", text, render_text(condition))
        parts.append(text)
    return format_html_join(", ", "{}", ((part,) for part in parts))


def _format_range(range_data):
    return units.range_label(spell_service.range_label(range_data))


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


def _index_letter(name: str) -> str:
    """The alphabet-index letter a list item files under: its first letter, accents stripped and
    uppercased ("Àmbito" -> "A"), or "#" for a name that doesn't start with a letter/digit.
    """
    for char in unicodedata.normalize("NFKD", str(name)):
        if char.isalnum():
            return char.upper() if char.isalpha() else "#"
    return "#"


def _split_bookmarked(
    request, items: list[dict], bookmark_kind: str
) -> tuple[list[dict], list[dict]]:
    """`(rest, bookmarked)`: `items` (each with a `pk`, optionally its own `"kind"` override for a
    page mixing more than one `BOOKMARK_MODELS` kind - see `_list_page()`'s docstring) split by
    whether `request.user` has it bookmarked, with each item's own `"bookmarked"` flag set along
    the way. Callers must only call this once `request.user.is_authenticated` - shared by
    `_list_page()` (the World lists) and the character sheet's own Features tab
    (`character_sheet._features_tab()`), which reads the exact same `Bookmark` rows under the same
    kinds ("feat"/"feature") so a bookmark set from either page shows up on the other.
    """
    ids_by_kind: dict[str, set[str]] = {}
    for item in items:
        kind = item.get("kind", bookmark_kind)
        if item.get("pk") is None:
            item["bookmarked"] = False
            continue
        if kind not in ids_by_kind:
            ids_by_kind[kind] = bookmarked_ids(request.user, kind)
        # `Bookmark.object_id` is a `CharField` (every bookmarkable model but `Feature` has a
        # string slug pk to match it verbatim) - `Feature`'s own pk is a plain int, so it needs
        # `str()` here or it would never compare equal to anything in `ids_by_kind`.
        item["bookmarked"] = str(item["pk"]) in ids_by_kind[kind]
    bookmarked = [item for item in items if item["bookmarked"]]
    rest = [item for item in items if not item["bookmarked"]]
    return rest, bookmarked


def _list_page(
    request,
    title,
    items,
    back_url_name: str | None = None,
    world_tabs=False,
    handbook_tabs=False,
    image_vignette=False,
    compact_thumbs=False,
    search_query: str | None = None,
    search_placeholder: str | None = None,
    filters=(),
    searchable=False,
    alphabet=False,
    bookmark_kind: str | None = None,
    groups=(),
):
    """A list page is a root of its navigation menu (a World tab, the Handbook's Chapters/Glossary
    tabs), so it has no back button unless `back_url_name` names a parent. `searchable` shows the
    search box (and `filters` under it) without the category tabs that `world_tabs`/`handbook_tabs`
    also bring with it. `alphabet` adds the right-hand A-Z jump strip (each item then needs a
    `letter`, see `_index_letter()`). `bookmark_kind` (a `BOOKMARK_MODELS` key) gives every item
    with a `pk` a bookmark button, and moves the bookmarked ones out of `items` into
    `bookmarked_items`, shown as a highlighted block at the top of the list (only while signed in -
    see `account()`). An item on a page mixing more than one kind of row (e.g. the Features list's
    Feats alongside Class/Subclass Features and Species Traits) can override `bookmark_kind` with
    its own `"kind"` - `_list_item.html` then also renders a per-item hidden `kind` input (`form`-
    associated to the shared bookmark form, placed after it in the DOM) so both a plain submit and
    `new FormData(form)` pick up that override instead of the page's shared default, per the HTML
    forms spec collecting listed/associated elements in tree order. `groups` (the Handbook's
    chapters, each `{"key", "name", "items"}`) replaces the plain list with one toggle heading per
    group over that group's buttons.
    """
    # Letters (and their jump targets) come from every entry, bookmarked or not.
    alphabet_letters = list(dict.fromkeys(item["letter"] for item in items)) if alphabet else []
    bookmarked_items = []
    if not request.user.is_authenticated:
        bookmark_kind = None  # bookmarks are per account: nothing to show or toggle signed out
    if bookmark_kind:
        items, bookmarked_items = _split_bookmarked(request, items, bookmark_kind)

    context = {
        "page_title": _(title),
        "items": items,
        "bookmarked_items": bookmarked_items,
        "groups": groups,
        "bookmark_kind": bookmark_kind,
        # A first-timer's one-line explanation of the bookmark buttons: gone for good once they
        # have bookmarked anything, anywhere (or dismissed it - see `list.html`).
        "bookmark_hint": bool(bookmark_kind)
        and not Bookmark.objects.filter(user=request.user).exists(),
        "world_tabs": world_tabs,
        "handbook_tabs": handbook_tabs,
        "searchable": searchable,
        "image_vignette": image_vignette,
        "compact_thumbs": compact_thumbs,
        "alphabet": alphabet,
        "alphabet_letters": alphabet_letters,
    }
    if world_tabs or handbook_tabs or searchable:
        context["search_query"] = search_query or ""
        context["search_placeholder"] = search_placeholder
        context["filters"] = filters
    if back_url_name:
        context["back_url"] = reverse(back_url_name)
    response = render(request, "frontend/list.html", context)
    # Bookmarks change from other pages - never let back/forward navigation show a stale list.
    add_never_cache_headers(response)
    return response


def _search_query(request) -> str:
    return request.GET.get("q", "").strip()


def _text_snippets(obj, fields, pattern, limit=2) -> list:
    """Snippets (see `handbook_search`) of where `pattern` is in the text of `obj`'s `entries`-
    shaped `fields` - the active language's text first, then the other's, so an English word is
    found from the Italian site too (like `_by_name()` does for names). Empty if it is nowhere.
    """
    languages = ["it", "en"] if (get_language() or "en").startswith("it") else ["en", "it"]
    for language in languages:
        snippets = []
        for field in fields:
            value = getattr(obj, f"{field}_{language}", None)
            if value:
                snippets += find_hits(value, pattern, limit - len(snippets))[0]
            if len(snippets) >= limit:
                break
        if snippets:
            return snippets
    return []


def _text_matches(rows, q: str, fields, *, name=True):
    """`(row, snippets)` for each of `rows` whose name (unless `name=False`) or `fields` text
    contains `q` - what the World's Backgrounds/Classes/Species searches use instead of a bare
    name filter, so the descriptions are searched too."""
    pattern = query_pattern(q)
    for row in rows:
        snippets = _text_snippets(row, fields, pattern)
        if snippets or (name and name_matches(row, pattern)):
            yield row, snippets


def _hit_detail(text: str, snippets: list):
    """A row's detail line: its own `text`, then the snippets of where the query was found."""
    return format_html("{}{}", text, mark_safe("".join(snippets)))


def _by_name(queryset, q: str):
    """Rows whose English *or* Italian name contains `q` - a plain name filter only looks in the
    active language's column, so an English name wouldn't be found from the Italian site (and a
    row with no Italian name yet would never match at all).
    """
    return queryset.filter(Q(name_en__icontains=q) | Q(name_it__icontains=q))


def _pill_filter(request, name, label, options, *, all_label=None, only=None, multiple=False):
    """One `{kind, name, label, value, options, all_label}` entry for `_list_page`'s `filters` -
    a single-select row of clickable pills (radio inputs under the hood, one implicit "any" pill
    first, labeled `all_label`) in the world-search form (see base.html). `value` is read
    straight from `?<name>=...` here so callers only have to build the options and apply the
    filter to their queryset, not thread the selected value through separately.

    `only` (space-separated values of another filter's own name, e.g. a `name="section"` pill's
    "weapons") makes this filter conditional on that other filter's current value, the same
    `only` a `_checklist_filter()` already carries for the character sheet's own item browser
    (see `character_sheet.py`'s local `checkbox()`) - `_search_form.html` starts it `hidden`
    unconditionally whenever `only` is set, and JS (`filterRows()` there, `syncOnlyFilters()` in
    base.html here) reveals the right one once it knows the controlling filter's value.

    `multiple` makes the pills toggles instead (checkboxes, no "any" pill - none picked means no
    filter): the picked ones are `values`, read with `getlist`.
    """
    return {
        "kind": "radio",
        "multiple": multiple,
        "name": name,
        "values": {v.strip() for v in request.GET.getlist(name) if v.strip()},
        "label": label,
        "value": request.GET.get(name, "").strip(),
        "options": options,
        "all_label": all_label or _("All"),
        "only": only,
    }


def _select_filter(request, name, label, options, *, all_label=None, only=None, filter_by=None):
    """Dropdown sibling of `_pill_filter()`: a native `<select>` for a single choice from a list
    too long for a pill row (e.g. every Class, or Level 1-20) - see `_search_form.html`'s
    `kind == "select"` block. `only` is the same conditional-visibility mechanism `_pill_filter()`
    documents.

    `filter_by` (another select filter's own `name`, e.g. "class") narrows this one's own options
    to those relevant to whatever that other select currently holds - each option then carries a
    third tuple element (its owning group's value, e.g. a Subclass option's `klass_id`) instead of
    a plain `(value, label)` pair. `_search_form.html` puts that on a `data-group` attribute, and
    `syncGroupedOptions()` in base.html hides every option whose group doesn't match the
    controlling select's current value (and clears this select if its own choice just got hidden).
    """
    return {
        "kind": "select",
        "name": name,
        "label": label,
        "value": request.GET.get(name, "").strip(),
        "options": options,
        "all_label": all_label or _("All"),
        "only": only,
        "filter_by": filter_by,
    }


def _checklist_filter(request, name, label, options):
    """Multi-select sibling of `_pill_filter()`: a filter button that opens a popover of
    checkboxes, `?<name>=` read with `getlist` so more than one value can be selected at once
    (e.g. Spell level/school).
    """
    return {
        "kind": "checkbox",
        "name": name,
        "label": label,
        "values": set(request.GET.getlist(name)),
        "options": options,
    }


def _self_translated(obj, *fields: str) -> bool:
    """True when any of `obj`'s given field(s) was hand-translated for this project rather than
    lifted from the official Italian SRD (see `Feature.self_translated_fields`'s docstring) - only
    worth flagging while actually browsing in Italian, since the flag says nothing about the
    English text. Callers pass the specific field(s) a page section is actually built from (e.g.
    `"lore"` for a Lore section, `"name"` for the page title) rather than checking the row as a
    whole, so a page that's only partly hand-translated doesn't have every section flagged.
    """
    if get_language() != "it":
        return False
    self_translated_fields = set(getattr(obj, "self_translated_fields", None) or ())
    return bool(self_translated_fields & set(fields))


def _badged_heading(label, is_self_translated: bool):
    """`label`, with a "Traduzione" badge appended when `is_self_translated` - for a
    `plain_sections` heading built from a hand-translated field (see `_self_translated()`).
    """
    badge = self_translated_badge(is_self_translated)
    return mark_safe(f"{escape(label)}{badge}") if badge else label


def _homebrew_heading(label):
    """`label` with a "Homebrew" badge appended, in every language - for a species that isn't
    part of the official 2024 rules (see `HOMEBREW_SPECIES`).
    """
    return mark_safe(f"{escape(label)}{homebrew_badge()}")


def _detail_page(
    request,
    title,
    back_url_name,
    facts,
    body=None,
    plain_sections=(),
    tabs=None,
    active_tab=None,
    bookmark: tuple[str, str] | None = None,
):
    # `bookmark` is `(kind, pk)` for a page with the header's bookmark button (see `Bookmark`).
    # `title` may already be a `_badged_heading()` result (safe HTML with an inline "Traduzione"
    # badge) - passed straight through as `page_title` rather than a separate flag, so the badge
    # sits on the specific thing that's hand-translated (the row's own `name`) instead of a
    # page-wide flag that would show even while looking at an unrelated, officially-translated tab.
    context = {
        "page_title": title,
        "back_url": reverse(back_url_name),
        "facts": facts,
        "body": body,
        "plain_sections": plain_sections,
        "tabs": tabs,
        "active_tab": active_tab,
    }
    if bookmark and request.user.is_authenticated:
        kind, object_id = bookmark
        context["bookmark"] = {
            "kind": kind,
            "id": object_id,
            "active": is_bookmarked(request.user, kind, object_id),
        }
    response = render(request, "frontend/detail.html", context)
    add_never_cache_headers(response)
    return response


def _active_tab(request, tabs, default: str) -> str:
    """Resolve the `?tab=` query param against a page's own `tabs` keys, falling back to
    `default` for a missing/unknown value instead of erroring - lets a stale/hand-typed link
    still land on a real tab rather than a blank page.
    """
    requested = request.GET.get("tab")
    valid_keys = {key for key, _label in tabs}
    return requested if requested in valid_keys else default


def _safe_next_url(request, default_url_name: str) -> str:
    """The `next` param (POST body, else query string) if it's a same-site URL, else the
    `default_url_name` page - never an open redirect."""
    next_url = request.POST.get("next") or request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return reverse(default_url_name)


def account(request):
    """Password-less sign-in (see `accounts.py`), or - once signed in - who you are and a
    sign-out button."""
    next_url = _safe_next_url(request, "world-overview")
    form = None
    if not request.user.is_authenticated:
        form = SignInForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            user = accounts.get_or_create_passwordless_user(form.cleaned_data["username"])
            if user is None:
                form.add_error("username", _("This name can't be used to sign in."))
            else:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                return redirect(next_url)
    response = render(
        request,
        "frontend/account.html",
        {
            "page_title": _("Account") if form is None else _("Sign in"),
            "back_url": next_url,
            "form": form,
            "next_url": next_url,
            "is_admin": access.is_admin(request.user),
            "access_logout_url": cloudflare_access.logout_url()
            if cloudflare_access.is_enabled()
            else "",
        },
    )
    add_never_cache_headers(response)
    return response


def welcome(request):
    """First sign-in through Cloudflare Access: the account exists but has no name yet, so ask
    for one (`RequireNameMiddleware` sends every page here until it is given)."""
    next_url = _safe_next_url(request, "index")
    if not request.user.is_authenticated:
        return redirect(reverse("account"))
    form = NameForm(request.POST or None, initial={"name": request.user.first_name})
    if request.method == "POST" and form.is_valid():
        request.user.first_name = form.cleaned_data["name"]
        request.user.save(update_fields=["first_name"])
        return redirect(next_url)
    response = render(
        request,
        "frontend/welcome.html",
        {"page_title": _("Welcome"), "form": form, "next_url": next_url},
    )
    add_never_cache_headers(response)
    return response


@require_POST
def account_logout(request):
    logout(request)
    return redirect(_safe_next_url(request, "index"))


@require_POST
def bookmark_toggle(request):
    ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if not request.user.is_authenticated:
        # Stale page from before signing out (the buttons aren't rendered signed out).
        if ajax:
            return JsonResponse({"error": "sign in required"}, status=401)
        return redirect(
            f"{reverse('account')}?next={quote(_safe_next_url(request, 'world-overview'))}"
        )

    kind = request.POST.get("kind", "")
    object_id = request.POST.get("object_id", "")
    if ":" in object_id:  # an entry of another kind than the list's own: "<kind>:<pk>"
        kind, object_id = object_id.split(":", 1)
    model = BOOKMARK_MODELS.get(kind)
    if model is None or not object_id:
        raise Http404
    try:
        exists = model.objects.filter(pk=object_id).exists()
    except (ValueError, TypeError):  # e.g. a slug sent for `Feature`, whose pk is an integer
        exists = False
    if not exists:
        raise Http404
    _bookmark, created = Bookmark.objects.get_or_create(
        user=request.user, kind=kind, object_id=object_id
    )
    if not created:
        _bookmark.delete()

    # The header button's script posts in the background and just flips its own icon; a plain
    # form post (JS off/slow) falls back to redirecting back to the page it came from.
    if ajax:
        return JsonResponse({"bookmarked": created})
    return redirect(_safe_next_url(request, "world-overview"))


# --- Handbook ----------------------------------------------------------------------------


def handbook_overview(request):
    q = _search_query(request)
    if q:
        return _handbook_search(request, q)
    # Below the tabs and the search box, each `HandbookChapter` is a toggle heading over the
    # buttons of its sections.
    groups = [
        {
            "key": chapter.pk,
            "name": chapter.name,
            "items": [
                {
                    "name": _badged_heading(section.name, _self_translated(section, "name")),
                    # Drawn as a "Page N" detail line (`_list_item.html`).
                    "page": section.page,
                    "url": reverse("handbook-section-detail", args=[section.pk]),
                }
                for section in chapter.sections.all()
            ],
        }
        for chapter in handbook_service.list_chapters()
    ]
    return _list_page(
        request,
        "Handbook",
        [],
        groups=groups,
        handbook_tabs=True,
        searchable=True,
        search_placeholder=_("Search the handbook"),
    )


def _handbook_search(request, q: str):
    """The Handbook's Chapters tab while searching: the same chapter toggles, but holding only the
    sections whose name or text contains `q` (each with snippets of where), followed by the
    Glossary rules that match - under the same tabs and search box. See `handbook_search`.
    """
    pattern = query_pattern(q)
    groups = []
    for chapter in handbook_service.list_chapters():
        items = []
        for section in chapter.sections.all():
            snippets, total = find_hits(section.entries, pattern)
            if not (snippets or name_matches(section, pattern)):
                continue
            more = total - len(snippets)
            if more:
                snippets.append(
                    format_html(
                        '<span class="hit">{}</span>', _("+%(count)d more") % {"count": more}
                    )
                )
            items.append(
                {
                    "name": _badged_heading(section.name, _self_translated(section, "name")),
                    "page": section.page,
                    "detail": mark_safe("".join(snippets)),
                    "url": reverse("handbook-section-detail", args=[section.pk]),
                }
            )
        if items:
            # Keys are prefixed so a chapter folded on the contents page doesn't start out folded
            # here too (see the fold-state script in list.html).
            groups.append({"key": f"search-{chapter.pk}", "name": chapter.name, "items": items})

    rule_items = []
    for rule in rule_service.list_rules():
        snippets, _total = find_hits(rule.entries, pattern, limit=1)
        if snippets or name_matches(rule, pattern):
            rule_items.append(
                {
                    "name": _badged_heading(rule.name, _self_translated(rule, "name")),
                    "page": rule.page,
                    "detail": mark_safe("".join(snippets)),
                    "url": reverse("world-rule-detail", args=[rule.pk]),
                }
            )
    if rule_items:
        groups.append({"key": "search-glossary", "name": _("Glossary"), "items": rule_items})

    return _list_page(
        request,
        "Handbook",
        [],
        groups=groups,
        handbook_tabs=True,
        searchable=True,
        search_query=q,
        search_placeholder=_("Search the handbook"),
    )


def handbook_rules_glossary(request):
    q = _search_query(request)
    rules = rule_service.list_rules()
    if q:
        rules = _by_name(rules, q)
    items = [
        {
            "pk": rule.pk,
            "name": _badged_heading(rule.name, _self_translated(rule, "name")),
            # A "Page N" detail line (`_list_item.html`), same as a Handbook chapter's sections.
            "page": rule.page,
            "url": reverse("world-rule-detail", args=[rule.pk]),
            "letter": _index_letter(rule.name),
        }
        for rule in rules
    ]
    return _list_page(
        request,
        "Glossary",
        items,
        handbook_tabs=True,
        searchable=True,
        search_query=q,
        search_placeholder=_("Search glossary"),
        alphabet=True,
        bookmark_kind="rule",
    )


def handbook_section_detail(request, pk):
    section = handbook_service.get_section(pk)
    facts = [(_("Page"), section.page)]
    body = render_handbook_section(section.entries)
    title = _badged_heading(section.name, _self_translated(section, "name"))
    return _detail_page(request, title, "handbook-overview", facts, body=body)


# --- Backgrounds --------------------------------------------------------------------------


def world_backgrounds(request):
    q = _search_query(request)
    backgrounds = [(b, []) for b in background_service.list_backgrounds()]
    if q:
        backgrounds = _text_matches(background_service.list_backgrounds(), q, ("lore", "entries"))
    items = [
        {
            "pk": b.pk,
            "name": _badged_heading(b.name, _self_translated(b, "name")),
            "detail": _hit_detail(b.short_description, hits),
            "url": reverse("world-background-detail", args=[b.pk]),
            "image": _menu_image_url(
                "backgrounds", f"{_BACKGROUND_IMAGE_SLUGS.get(b.id, b.id)}.jpeg"
            ),
        }
        for b, hits in backgrounds
    ]
    return _list_page(
        request,
        "Backgrounds",
        items,
        world_tabs=True,
        image_vignette=True,
        search_query=q,
        search_placeholder=_("Search backgrounds"),
        bookmark_kind="background",
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
        feat_url = reverse("world-feat-detail", args=[bg.feat.pk])
        facts.append((_("Feat"), format_html('<a href="{}">{}</a>', feat_url, bg.feat.name)))
    if starting_equipment:
        facts.append((_("Starting Equipment"), render_starting_equipment(starting_equipment)))
    facts.append((_("Page"), bg.page))

    plain_sections = []
    if bg.lore:
        heading = _badged_heading(_("Lore"), _self_translated(bg, "lore"))
        plain_sections.append((heading, render_entries(bg.lore)))

    return _detail_page(
        request,
        _badged_heading(bg.name, _self_translated(bg, "name")),
        "world-backgrounds",
        facts,
        plain_sections=plain_sections,
        bookmark=("background", bg.pk),
    )


# --- Classes --------------------------------------------------------------------------------


def world_classes(request):
    q = _search_query(request)
    classes = [(c, []) for c in class_service.list_classes()]
    if q:
        classes = _text_matches(class_service.list_classes(), q, ("lore",))
    items = [
        {
            "pk": c.pk,
            "name": _badged_heading(c.name, _self_translated(c, "name")),
            "detail": _hit_detail(c.short_description, hits),
            "url": reverse("world-class-detail", args=[c.pk]),
            "image": _menu_image_url("classes", f"{c.id}-grey.webp"),
        }
        for c, hits in classes
    ]
    if q:
        # A class's own name isn't repeated in these two sub-object results (unlike the
        # `detail` above) - the class itself already appears as its own top-level `items` entry
        # when it matches, so its name lives in `item-name`, not `item-detail`, either way.
        # Their names and the text of their descriptions are searched, with snippets of where.
        items += [
            {
                "name": _badged_heading(sc.name, _self_translated(sc, "name")),
                "detail": _hit_detail(_("Subclass of %(klass)s") % {"klass": sc.klass.name}, hits),
                "url": f"{reverse('world-class-detail', args=[sc.klass_id])}?tab=subclasses",
            }
            for sc, hits in _text_matches(
                Subclass.objects.select_related("klass"), q, ("description",)
            )
        ]
        items += [
            {
                "name": _badged_heading(feature.name, _self_translated(feature, "name")),
                "detail": _hit_detail(
                    _("Feature of %(klass)s (Level %(level)s)")
                    % {
                        "klass": feature.class_level.klass.name,
                        "level": feature.class_level.level,
                    },
                    hits,
                ),
                "url": reverse("world-feature-detail", args=[feature.pk]),
            }
            for feature, hits in _text_matches(
                Feature.objects.filter(class_level__isnull=False).select_related(
                    "class_level__klass"
                ),
                q,
                ("entries",),
            )
        ]
        items += [
            {
                "name": _badged_heading(feature.name, _self_translated(feature, "name")),
                "detail": _hit_detail(
                    _("Feature of %(klass)s") % {"klass": feature.subclass_level.subclass.name},
                    hits,
                ),
                "url": reverse("world-feature-detail", args=[feature.pk]),
            }
            for feature, hits in _text_matches(
                Feature.objects.filter(subclass_level__isnull=False).select_related(
                    "subclass_level__subclass"
                ),
                q,
                ("entries",),
            )
        ]
    return _list_page(
        request,
        "Classes",
        items,
        world_tabs=True,
        search_query=q,
        search_placeholder=_("Search classes"),
        bookmark_kind="class",
    )


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
            heading = _badged_heading(_("Lore"), _self_translated(klass, "lore"))
            # `klass.lore` is always a single top-level node whose own `name` just repeats the
            # class's name (e.g. `[{"type": "section", "name": "Barbarian", "entries": [...]}]`,
            # verified against every class in db/fluff-classes.json and db/it/classes.json) -
            # already redundant with the "Lore" heading above it and the page's own title, so
            # only its nested `entries` (the actual prose) gets rendered.
            lore_entries = klass.lore
            wrapper = lore_entries[0] if len(lore_entries) == 1 else None
            if isinstance(wrapper, dict) and wrapper.get("name"):
                lore_entries = wrapper.get("entries", [])
            plain_sections.append((heading, render_entries(lore_entries)))

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
                            # Straight to the feature's own page (its text no longer lives on the
                            # Levels tab - see `world_feature_detail()`).
                            {
                                "name": f.name,
                                "href": reverse("world-feature-detail", args=[f.pk]),
                            }
                            for f in features_by_level.get(lvl.level, [])
                        ],
                    },
                }
                # `lvl.columns`' own keys are the source's English column names (e.g. "Rages",
                # "Unarmored Movement") - `gettext()` translates the ones the .po file covers
                # (every class-specific column the SRD names) and passes anything else through
                # unchanged, same as any other `_()` call with no matching msgid.
                row.update({_(column): value for column, value in lvl.columns.items()})
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
        _badged_heading(klass.name, _self_translated(klass, "name")),
        "world-classes",
        facts,
        body=body,
        plain_sections=plain_sections,
        tabs=tabs,
        active_tab=active_tab,
        bookmark=("class", klass.pk),
    )


# --- Feats -----------------------------------------------------------------------------------


def world_feats(request):
    q = _search_query(request)
    type_filter = _pill_filter(
        request,
        "type",
        _("Type"),
        [
            ("feat", _("Feats")),
            ("class", _("Class Features")),
            ("subclass", _("Subclass Features")),
            ("species", _("Species Traits")),
        ],
        multiple=True,
    )
    # Several types can be ticked at once; none ticked means all of them.
    selected_types = type_filter["values"]

    def wants(*types):
        return not selected_types or bool(selected_types & set(types))

    # Each of these is only relevant to (and only shown for) one specific `type` pill - see
    # `_pill_filter()`'s docstring on `only` and the `data-only` sync script in base.html. Built
    # unconditionally (not just while its own type is selected) so the page can still render
    # every filter's options up front - the base.html script reveals the right one with no
    # reload the moment `type` changes, instead of re-fetching this whole form.
    category_filter = _pill_filter(
        request,
        "category",
        _("Category"),
        [(c, _format_feat_category(c)) for c in feat_service.list_categories()],
        only="feat",
        multiple=True,
    )
    level_filter = _select_filter(
        request,
        "level",
        _("Level"),
        [(str(n), f"{_('Level')} {n}") for n in range(1, 21)],
        all_label=_("All levels"),
        only="class subclass",
    )
    class_filter = _select_filter(
        request,
        "class",
        _("Class"),
        [(c.pk, c.name) for c in class_service.list_classes()],
        all_label=_("All classes"),
        only="class subclass",
    )
    subclass_filter = _select_filter(
        request,
        "subclass",
        _("Subclass"),
        [(sc.pk, sc.name, sc.klass_id) for sc in Subclass.objects.all()],
        all_label=_("All subclasses"),
        only="subclass",
        filter_by="class",
    )
    species_filter = _select_filter(
        request,
        "species",
        _("Species"),
        [(s.pk, s.name) for s in species_service.list_species()],
        all_label=_("All species"),
        only="species",
    )
    items = []

    if wants("feat"):
        feats = feat_service.list_feats()
        if q:
            feats = _by_name(feats, q)
        if "feat" in selected_types and category_filter["values"]:
            feats = feat_service.matching_categories(feats, category_filter["values"])
        items += [
            {
                "pk": f.pk,
                "name": _badged_heading(f.name, _self_translated(f, "name")),
                "properties": [_("Feat"), _format_feat_category(f.category)],
                "url": reverse("world-feat-detail", args=[f.pk]),
                # "Fighting Style (P)"/"(R)" sub-variants share their base category's artwork.
                "image": _menu_image_url(
                    "feats", f"{f.category.split(' (')[0].lower().replace(' ', '_')}.jpeg"
                ),
            }
            for f in feats
        ]

    if wants("class"):
        # Every class repeats "Ability Score Improvement" at the same handful of levels - noise
        # in a list of things to look up, so it's left out (matched on the English name, whatever
        # the active language).
        class_features = (
            Feature.objects.filter(class_level__isnull=False)
            .exclude(name_en="Ability Score Improvement")
            .select_related("class_level__klass")
        )
        if q:
            class_features = _by_name(class_features, q)
        if "class" in selected_types:
            if level_filter["value"]:
                class_features = class_features.filter(class_level__level=level_filter["value"])
            if class_filter["value"]:
                class_features = class_features.filter(class_level__klass_id=class_filter["value"])
        items += [
            {
                "pk": feature.pk,
                "kind": "feature",
                "name": _badged_heading(feature.name, _self_translated(feature, "name")),
                "properties": [
                    _("Class"),
                    feature.class_level.klass.name,
                    f"{_('Level')} {feature.class_level.level}",
                ],
                "url": reverse("world-feature-detail", args=[feature.pk]),
                "image": _menu_image_url(
                    "features_classes", f"{feature.class_level.klass_id}.jpeg"
                ),
            }
            for feature in class_features
        ]

    if wants("subclass"):
        subclass_features = Feature.objects.filter(subclass_level__isnull=False).select_related(
            "subclass_level__subclass__klass"
        )
        if q:
            subclass_features = _by_name(subclass_features, q)
        if "subclass" in selected_types:
            if level_filter["value"]:
                subclass_features = subclass_features.filter(
                    subclass_level__level=level_filter["value"]
                )
            if class_filter["value"]:
                subclass_features = subclass_features.filter(
                    subclass_level__subclass__klass_id=class_filter["value"]
                )
            if subclass_filter["value"]:
                subclass_features = subclass_features.filter(
                    subclass_level__subclass_id=subclass_filter["value"]
                )
        for feature in subclass_features:
            klass_id = feature.subclass_level.subclass.klass_id
            items.append(
                {
                    "pk": feature.pk,
                    "kind": "feature",
                    "name": _badged_heading(feature.name, _self_translated(feature, "name")),
                    "properties": [
                        _("Subclass"),
                        feature.subclass_level.subclass.name,
                        f"{_('Level')} {feature.subclass_level.level}",
                    ],
                    "url": reverse("world-feature-detail", args=[feature.pk]),
                    "image": _menu_image_url("features_subclasses", f"{klass_id}.jpg"),
                    "image_class": "subclass-icon",
                }
            )

    if wants("species"):
        species_traits = Feature.objects.filter(species__isnull=False).select_related("species")
        if q:
            species_traits = _by_name(species_traits, q)
        if "species" in selected_types and species_filter["value"]:
            species_traits = species_traits.filter(species_id=species_filter["value"])
        items += [
            {
                "pk": trait.pk,
                "kind": "feature",
                "name": _badged_heading(trait.name, _self_translated(trait, "name")),
                "properties": [_("Species"), trait.species.name],
                "url": reverse("world-feature-detail", args=[trait.pk]),
                "image": _menu_image_url(
                    "features_species",
                    f"{_SPECIES_IMAGE_SLUGS.get(trait.species_id, trait.species_id)}.jpg",
                ),
            }
            for trait in species_traits
        ]

    # One flat alphabetical list rather than grouped by type - `name` may be a `_badged_heading()`
    # result (safe HTML, an escaped name plus a trailing badge), but comparing its string form
    # still sorts correctly since the name itself is always the leading text.
    items.sort(key=lambda item: str(item["name"]).casefold())

    return _list_page(
        request,
        "Features",
        items,
        world_tabs=True,
        compact_thumbs=True,
        search_query=q,
        search_placeholder=_("Search features, feats and traits"),
        filters=[
            type_filter,
            category_filter,
            level_filter,
            class_filter,
            subclass_filter,
            species_filter,
        ],
        bookmark_kind="feat",
    )


def world_feature_detail(request, pk):
    """A class/subclass feature or species trait's own page - a `Feature` row's `entries`
    rendered the same way a Feat's are, since the merged Features list (`world_feats()`) links
    every non-Feat entry here now instead of into its parent Class/Species page's own tab.
    """
    feature = feature_service.get_feature(pk)

    facts = []
    if feature.class_level_id:
        klass = feature.class_level.klass
        facts.append(
            (
                _("Class"),
                format_html(
                    '<a href="{}">{}</a>',
                    reverse("world-class-detail", args=[klass.pk]),
                    klass.name,
                ),
            )
        )
        facts.append((_("Level"), feature.class_level.level))
    elif feature.subclass_level_id:
        subclass = feature.subclass_level.subclass
        class_url = reverse("world-class-detail", args=[subclass.klass_id])
        facts.append(
            (_("Class"), format_html('<a href="{}">{}</a>', class_url, subclass.klass.name))
        )
        facts.append(
            (
                _("Subclass"),
                format_html('<a href="{}">{}</a>', f"{class_url}?tab=subclasses", subclass.name),
            )
        )
        facts.append((_("Level"), feature.subclass_level.level))
    elif feature.species_id:
        species = feature.species
        facts.append(
            (
                _("Species"),
                format_html(
                    '<a href="{}">{}</a>',
                    reverse("world-species-detail", args=[species.pk]),
                    species.name,
                ),
            )
        )

    description_heading = _badged_heading(_("Description"), _self_translated(feature, "entries"))
    plain_sections = [(description_heading, render_entries(feature.entries))]

    return _detail_page(
        request,
        _badged_heading(feature.name, _self_translated(feature, "name")),
        "world-feats",
        facts,
        plain_sections=plain_sections,
    )


def world_option_detail(request, pk):
    """An Options pick's (Eldritch Invocation, Metamagic, Battle Master Maneuver) own page - not
    reachable from any World list (there isn't one for these), only from a character's own
    Features tab, but otherwise built the same way as a Feat's or a `Feature`'s own page.

    No "Prerequisite" fact: `OptionalFeature.prerequisite` isn't shaped like `Feat.prerequisite`
    despite the shared name (its `level` is a `{level, class}` dict, not a bare int, and it has
    two keys - `spell`, `optionalfeature` - `_format_prerequisite()` doesn't handle at all) -
    verified against every one of the 58 rows in db/optionalfeatures.json. Showing it would need
    its own formatter for a fact that's usually redundant with the description text anyway (most
    rows - 35/58 - have none at all), so it's left off rather than rendered wrong.
    """
    option = optional_feature_service.get_optional_feature(pk)

    facts = []
    klass_id = _option_class_id(option)
    if klass_id:
        klass = class_service.get_class(klass_id)
        facts.append(
            (
                _("Class"),
                format_html(
                    '<a href="{}">{}</a>',
                    reverse("world-class-detail", args=[klass.pk]),
                    klass.name,
                ),
            )
        )
    facts.append((_("Page"), option.page))

    description_heading = _badged_heading(_("Description"), _self_translated(option, "entries"))
    plain_sections = [(description_heading, render_entries(option.entries))]

    return _detail_page(
        request,
        _badged_heading(option.name, _self_translated(option, "name")),
        "world-feats",
        facts,
        plain_sections=plain_sections,
        bookmark=("option", option.pk),
    )


def world_feat_detail(request, pk):
    feat = feat_service.get_feat(pk)

    facts = [(_("Category"), _format_feat_category(feat.category))]
    if feat.prerequisite:
        facts.append((_("Prerequisite"), _format_prerequisite(feat.prerequisite)))
    if ability := _format_feat_ability(feat.ability):
        facts.append((_("Ability Score Increase"), ability))
    facts.append((_("Page"), feat.page))

    description_heading = _badged_heading(_("Description"), _self_translated(feat, "entries"))
    plain_sections = [(description_heading, render_entries(feat.entries))]

    return _detail_page(
        request,
        _badged_heading(feat.name, _self_translated(feat, "name")),
        "world-feats",
        facts,
        plain_sections=plain_sections,
        bookmark=("feat", feat.pk),
    )


# --- Species ---------------------------------------------------------------------------------


#: Species that aren't official 2024 content (`Grung` is Volo's Guide, converted by hand - see
#: `SPECIES_SHORT_DESCRIPTIONS` in `import_rules_data.py`). They get a "Homebrew" badge in place of
#: the "Traduzione" one: their Italian text is hand-translated by definition, so flagging that as
#: well would only repeat what "Homebrew" already says.
HOMEBREW_SPECIES = frozenset({"grung"})


def _species_heading(species):
    """A species' name, badged "Homebrew" or (in Italian, if hand-translated) "Traduzione"."""
    if species.pk in HOMEBREW_SPECIES:
        return _homebrew_heading(species.name)
    return _badged_heading(species.name, _self_translated(species, "name"))


def world_species(request):
    q = _search_query(request)
    species_qs = [(sp, []) for sp in species_service.list_species()]
    if q:
        species_qs = _text_matches(species_service.list_species(), q, ("lore", "entries"))
    items = [
        {
            "pk": s.pk,
            "name": _species_heading(s),
            "detail": _hit_detail(s.short_description, hits),
            "url": reverse("world-species-detail", args=[s.pk]),
            "image": _menu_image_url(
                "species", f"{_SPECIES_IMAGE_SLUGS.get(s.id, s.id)}-grey.webp"
            ),
        }
        for s, hits in species_qs
    ]
    if q:
        items += [
            {
                "name": _badged_heading(trait.name, _self_translated(trait, "name")),
                "detail": _hit_detail(
                    _("Trait of %(species)s") % {"species": trait.species.name}, hits
                ),
                "url": f"{reverse('world-species-detail', args=[trait.species_id])}?tab=traits",
            }
            for trait, hits in _text_matches(
                Feature.objects.filter(species__isnull=False).select_related("species"),
                q,
                ("entries",),
            )
        ]
    return _list_page(
        request,
        "Species",
        items,
        world_tabs=True,
        search_query=q,
        search_placeholder=_("Search species"),
        bookmark_kind="species",
    )


def world_species_detail(request, pk):
    species = species_service.get_species(pk)

    tabs = [("about", _("About")), ("traits", _("Traits"))]
    active_tab = _active_tab(request, tabs, default="about")

    homebrew = species.pk in HOMEBREW_SPECIES
    facts = []
    plain_sections = []
    body = None

    if active_tab == "about":
        facts = [
            (_("Size"), _format_size(species.size)),
            (_("Speed"), units.distance(species.speed)),
            (_("Creature Type"), _format_creature_types(species.creature_types)),
        ]
        if species.darkvision:
            facts.append((_("Darkvision"), units.distance(species.darkvision)))
        facts.append((_("Page"), species.page))

        if species.lore:
            heading = _badged_heading(_("Lore"), not homebrew and _self_translated(species, "lore"))
            plain_sections.append((heading, render_entries(species.lore)))

    elif active_tab == "traits":
        if species.entries:
            feature_ids = {f.name: f.pk for f in species.feature_rows.all()}
            body = render_trait_cards(
                species.entries,
                self_translated=not homebrew and _self_translated(species, "entries"),
                feature_ids=feature_ids,
            )

    return _detail_page(
        request,
        _species_heading(species),
        "world-species",
        facts,
        body=body,
        plain_sections=plain_sections,
        tabs=tabs,
        active_tab=active_tab,
        bookmark=("species", species.pk),
    )


# --- Spells ----------------------------------------------------------------------------------


def world_spells(request):
    q = _search_query(request)
    level_filter = _checklist_filter(
        request,
        "level",
        _("Level"),
        [("0", _("Cantrip"))] + [(str(n), f"{_('Level')} {n}") for n in range(1, 10)],
    )
    class_filter = _checklist_filter(
        request, "class", _("Class"), [(c, _class_name(c)) for c in spell_service.list_classes()]
    )
    school_filter = _checklist_filter(
        request,
        "school",
        _("School"),
        [(s, _pick_translation(_SCHOOL_LABELS, s)) for s in spell_service.list_schools()],
    )
    range_filter = _checklist_filter(
        request,
        "range",
        _("Range"),
        # `k` (the raw English label) stays the filter's value - `range_kind()` matches querysets
        # against that same English text - only the displayed label goes metric.
        [(k, units.range_label(k)) for k in spell_service.list_range_kinds()],
    )
    casting_time_filter = _checklist_filter(
        request,
        "casting_time",
        _("Casting Time"),
        [
            (key, _pick_translation(_CASTING_TIME_FILTER_LABELS, label))
            for key, label in spell_service.list_casting_times()
        ],
    )
    save_filter = _checklist_filter(
        request, "save", _("Saving Throw"), [(a.id, a.name) for a in Ability.objects.all()]
    )

    spells = spell_service.list_spells()
    if q:
        spells = _by_name(spells, q)
    if level_filter["values"]:
        spells = spells.filter(level__in=[int(v) for v in level_filter["values"]])
    if class_filter["values"]:
        class_match = Q()
        for klass in class_filter["values"]:
            class_match |= Q(classes__contains=[klass])
        spells = spells.filter(class_match)
    if school_filter["values"]:
        spells = spells.filter(school__in=school_filter["values"])
    if save_filter["values"]:
        spells = spells.filter(saving_throw_abilities__id__in=save_filter["values"]).distinct()

    # `range`/`casting_time` are unindexed JSON shapes (see `Spell`'s docstring), not plain
    # columns a queryset filter can match against directly - `spell_service.range_kind()`/
    # `casting_time_keys()` derive the checklist-facet value per spell instead, cheap enough in
    # Python over the ~400-row catalog once the DB-level filters above have already narrowed it.
    spells = list(spells)
    if range_filter["values"]:
        spells = [s for s in spells if spell_service.range_kind(s) in range_filter["values"]]
    if casting_time_filter["values"]:
        spells = [
            s
            for s in spells
            if casting_time_filter["values"] & set(spell_service.casting_time_keys(s))
        ]

    items = []
    for s in spells:
        level_text = _("Cantrip") if s.level == 0 else f"{_('Level')} {s.level}"
        items.append(
            {
                "pk": s.pk,
                "name": _badged_heading(s.name, _self_translated(s, "name")),
                "detail": f"{level_text} · {_pick_translation(_SCHOOL_LABELS, s.school)}",
                "url": reverse("world-spell-detail", args=[s.pk]),
                # The image filename is keyed by the school's own *English* name (a fixed set of
                # asset files on disk), so this stays `s.school.lower()`, not the translated label.
                "image": _menu_image_url("spells", f"{s.school.lower()}.jpeg"),
            }
        )
    return _list_page(
        request,
        "Spells",
        items,
        world_tabs=True,
        compact_thumbs=True,
        search_query=q,
        search_placeholder=_("Search spells"),
        filters=[
            level_filter,
            class_filter,
            school_filter,
            range_filter,
            casting_time_filter,
            save_filter,
        ],
        bookmark_kind="spell",
    )


def world_spell_detail(request, pk):
    spell = spell_service.get_spell(pk)
    level_value = _("Cantrip") if spell.level == 0 else spell.level

    facts = [
        (_("Level"), level_value),
        (_("School"), _pick_translation(_SCHOOL_LABELS, spell.school)),
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
        facts.append((_("Classes"), _format_spell_classes(spell.classes)))
    facts.append((_("Page"), spell.page))

    description_heading = _badged_heading(_("Description"), _self_translated(spell, "entries"))
    plain_sections = [(description_heading, render_entries(spell.entries))]
    if spell.entries_higher_level:
        higher_level_heading = _badged_heading(
            _("At Higher Levels"), _self_translated(spell, "entries_higher_level")
        )
        plain_sections.append((higher_level_heading, render_entries(spell.entries_higher_level)))

    return _detail_page(
        request,
        _badged_heading(spell.name, _self_translated(spell, "name")),
        "world-spells",
        facts,
        plain_sections=plain_sections,
        bookmark=("spell", spell.pk),
    )


def world_items(request):
    from apps.frontend.character_sheet import _INVENTORY_SECTIONS, inventory_filters
    from apps.frontend.character_views import _card_line

    q = _search_query(request)
    filters = inventory_filters(request)
    picked = {f["name"]: f["values"] for f in filters if f["kind"] == "checkbox"}
    section = next(f["value"] for f in filters if f["name"] == "section")
    items_qs = (
        equipment_service.list_equipment().select_related("type").prefetch_related("masteries")
    )
    if q:
        items_qs = _by_name(items_qs, q)
    sections = {key: types for key, _label, types in _INVENTORY_SECTIONS}
    if section in sections:
        if sections[section]:
            items_qs = items_qs.filter(type_id__in=sections[section])
        else:  # "misc": every type no other section claims, and untyped items
            claimed = [t for types in sections.values() for t in types]
            items_qs = items_qs.exclude(type_id__in=claimed)
    # The per-section filters only count under their own section (the page resets them otherwise).
    if picked["type"]:
        items_qs = items_qs.filter(type_id__in=picked["type"])
    if section == "weapons":
        if picked["category"]:
            items_qs = items_qs.filter(weapon_category__in=picked["category"])
        if picked["property"]:
            items_qs = items_qs.filter(properties__in=picked["property"])
        if picked["mastery"]:
            items_qs = items_qs.filter(masteries__in=picked["mastery"])
        items_qs = items_qs.distinct()
    items = [
        {
            "pk": e.pk,
            "name": _badged_heading(e.name, _self_translated(e, "name")),
            "detail": _card_line("equipment", e),
            "url": reverse("world-item-detail", args=[e.pk]),
        }
        for e in items_qs
    ]
    return _list_page(
        request,
        "Items",
        items,
        world_tabs=True,
        compact_thumbs=True,
        search_query=q,
        search_placeholder=_("Search items"),
        filters=filters,
        bookmark_kind="equipment",
    )


def world_item_detail(request, pk):
    from apps.frontend.character_views import _describe_equipment

    item = equipment_service.get_equipment(pk)
    facts, sections = _describe_equipment(item.pk)
    return _detail_page(
        request,
        _badged_heading(item.name, _self_translated(item, "name")),
        "world-items",
        facts,
        body=mark_safe("".join(sections)) if sections else None,
        bookmark=("equipment", item.pk),
    )


# --- Rules -----------------------------------------------------------------------------------
# No dedicated browsing list for `rules.Rule` (that's not one of the seven categories asked
# for) - this page only exists as the landing spot for `{@variantrule ...}` links found inside
# other pages' text (see `apps.frontend.entries_render`), so "back" returns to the World hub
# rather than to any one specific list.


def world_rule_detail(request, pk):
    rule = rule_service.get_rule(pk)
    facts = [(_("Page"), rule.page)]
    description_heading = _badged_heading(_("Description"), _self_translated(rule, "entries"))
    plain_sections = [(description_heading, render_entries(rule.entries))]
    return _detail_page(
        request,
        _badged_heading(rule.name, _self_translated(rule, "name")),
        "world-overview",
        facts,
        plain_sections=plain_sections,
        bookmark=("rule", rule.pk),
    )
