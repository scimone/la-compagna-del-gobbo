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

from apps.frontend import accounts, units
from apps.frontend.bookmarks import BOOKMARK_MODELS, bookmarked_ids, is_bookmarked
from apps.frontend.entries_render import (
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
from apps.frontend.forms import SignInForm
from apps.frontend.models import Bookmark
from apps.rules.models import Ability, Class, Equipment, Feature, Subclass
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


def _format_flag_grant(raw_list):
    """A flat/choice proficiency-grant list shared by `Class.armor_proficiencies`/
    `weapon_proficiencies`/`tool_proficiencies` and `Background.tools` - each entry is either a
    plain `{"name": true}` flag or an ad hoc placeholder+count/filter shape.
    """
    parts = []
    for entry in raw_list or []:
        for key, value in entry.items():
            if value is True:
                parts.append(_proficiency_label(key))
            elif isinstance(value, int):
                choice = _pick_translation(_TOOL_CHOICE_LABELS, key)
                parts.append(f"{_('Choose')} {value}: {choice}")
            elif isinstance(value, dict):
                parts.append(_proficiency_label(key))
    return ", ".join(parts)


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


def _index_letter(name: str) -> str:
    """The alphabet-index letter a list item files under: its first letter, accents stripped and
    uppercased ("Àmbito" -> "A"), or "#" for a name that doesn't start with a letter/digit.
    """
    for char in unicodedata.normalize("NFKD", str(name)):
        if char.isalnum():
            return char.upper() if char.isalpha() else "#"
    return "#"


def _list_page(
    request,
    title,
    items,
    back_url_name: str | None = "world-overview",
    world_tabs=False,
    image_vignette=False,
    compact_thumbs=False,
    search_query: str | None = None,
    search_placeholder: str | None = None,
    filters=(),
    searchable=False,
    alphabet=False,
    bookmark_kind: str | None = None,
):
    """`searchable` shows the search box (and `filters` under it) without the World category tabs
    that `world_tabs` also brings with it. `alphabet` adds the right-hand A-Z jump strip (each
    item then needs a `letter`, see `_index_letter()`). `bookmark_kind` (a `BOOKMARK_MODELS` key)
    gives every item with a `pk` a bookmark button, and moves the bookmarked ones out of `items`
    into `bookmarked_items`, shown as a highlighted block at the top of the list (only while
    signed in - see `account()`).
    """
    # Letters (and their jump targets) come from every entry, bookmarked or not.
    alphabet_letters = list(dict.fromkeys(item["letter"] for item in items)) if alphabet else []
    bookmarked_items = []
    if not request.user.is_authenticated:
        bookmark_kind = None  # bookmarks are per account: nothing to show or toggle signed out
    if bookmark_kind:
        ids = bookmarked_ids(request.user, bookmark_kind)
        for item in items:
            item["bookmarked"] = item.get("pk") in ids
        bookmarked_items = [item for item in items if item["bookmarked"]]
        items = [item for item in items if not item["bookmarked"]]

    context = {
        "page_title": _(title),
        "items": items,
        "bookmarked_items": bookmarked_items,
        "bookmark_kind": bookmark_kind,
        "world_tabs": world_tabs,
        "searchable": searchable,
        "image_vignette": image_vignette,
        "compact_thumbs": compact_thumbs,
        "alphabet": alphabet,
        "alphabet_letters": alphabet_letters,
    }
    if world_tabs or searchable:
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


def _by_name(queryset, q: str):
    """Rows whose English *or* Italian name contains `q` - a plain name filter only looks in the
    active language's column, so an English name wouldn't be found from the Italian site (and a
    row with no Italian name yet would never match at all).
    """
    return queryset.filter(Q(name_en__icontains=q) | Q(name_it__icontains=q))


def _pill_filter(request, name, label, options, *, all_label=None):
    """One `{kind, name, label, value, options, all_label}` entry for `_list_page`'s `filters` -
    a single-select row of clickable pills (radio inputs under the hood, one implicit "any" pill
    first, labeled `all_label`) in the world-search form (see base.html). `value` is read
    straight from `?<name>=...` here so callers only have to build the options and apply the
    filter to their queryset, not thread the selected value through separately.
    """
    return {
        "kind": "radio",
        "name": name,
        "label": label,
        "value": request.GET.get(name, "").strip(),
        "options": options,
        "all_label": all_label or _("All"),
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
        },
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
    model = BOOKMARK_MODELS.get(kind)
    if model is None or not model.objects.filter(pk=object_id).exists():
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
    # The Rules Glossary sits first, ahead of every chapter section - the source book's own
    # "Rules Glossary" section is dropped entirely (see `HandbookSection`'s docstring/the
    # README's i18n section: it has no Italian SRD source to translate it from), but its actual
    # purpose - a named-rule/keyword index - is better served here anyway, by linking straight
    # into the already-translated `Rule` catalog instead of untranslatable static prose.
    rule_count = rule_service.list_rules().count()
    items = [
        {
            "name": _("Rules Glossary"),
            "detail": _("%(count)d named rules and keywords") % {"count": rule_count},
            "url": reverse("handbook-rules-glossary"),
            "featured": True,
        },
    ] + [
        {
            "name": section.name,
            "detail": f"{_('Page')} {section.page}",
            "url": reverse("handbook-section-detail", args=[section.pk]),
        }
        for section in handbook_service.list_sections()
    ]
    return _list_page(request, "Handbook", items, back_url_name="index")


def handbook_rules_glossary(request):
    q = _search_query(request)
    rules = rule_service.list_rules()
    if q:
        rules = _by_name(rules, q)
    items = [
        {
            "pk": rule.pk,
            "name": _badged_heading(rule.name, _self_translated(rule, "name")),
            "detail": f"{_('Page')} {rule.page}",
            "url": reverse("world-rule-detail", args=[rule.pk]),
            "letter": _index_letter(rule.name),
        }
        for rule in rules
    ]
    return _list_page(
        request,
        "Rules Glossary",
        items,
        back_url_name="handbook-overview",
        searchable=True,
        search_query=q,
        search_placeholder=_("Search rules"),
        alphabet=True,
        bookmark_kind="rule",
    )


def handbook_section_detail(request, pk):
    section = handbook_service.get_section(pk)
    facts = [(_("Page"), section.page)]
    body = render_handbook_section(section.entries)
    return _detail_page(request, section.name, "handbook-overview", facts, body=body)


# --- Backgrounds --------------------------------------------------------------------------


def world_backgrounds(request):
    q = _search_query(request)
    backgrounds = background_service.list_backgrounds()
    if q:
        backgrounds = _by_name(backgrounds, q)
    items = [
        {
            "pk": b.pk,
            "name": _badged_heading(b.name, _self_translated(b, "name")),
            "detail": b.short_description,
            "url": reverse("world-background-detail", args=[b.pk]),
            "image": _menu_image_url(
                "backgrounds", f"{_BACKGROUND_IMAGE_SLUGS.get(b.id, b.id)}.jpeg"
            ),
        }
        for b in backgrounds
    ]
    # No back button: `world-overview` (the default) now redirects straight back here (the
    # leftmost World tab), which would otherwise just bounce back to this same page.
    return _list_page(
        request,
        "Backgrounds",
        items,
        back_url_name=None,
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
    classes = class_service.list_classes()
    if q:
        classes = _by_name(classes, q)
    items = [
        {
            "pk": c.pk,
            "name": _badged_heading(c.name, _self_translated(c, "name")),
            "detail": c.short_description,
            "url": reverse("world-class-detail", args=[c.pk]),
            "image": _menu_image_url("classes", f"{c.id}-grey.png"),
        }
        for c in classes
    ]
    if q:
        # A class's own name isn't repeated in these two sub-object results (unlike the
        # `detail` above) - the class itself already appears as its own top-level `items` entry
        # when it matches, so its name lives in `item-name`, not `item-detail`, either way.
        subclasses = _by_name(Subclass.objects.all(), q).select_related("klass")
        items += [
            {
                "name": _badged_heading(sc.name, _self_translated(sc, "name")),
                "detail": _("Subclass of %(klass)s") % {"klass": sc.klass.name},
                "url": f"{reverse('world-class-detail', args=[sc.klass_id])}?tab=subclasses",
            }
            for sc in subclasses
        ]
        features = _by_name(Feature.objects.filter(class_level__isnull=False), q).select_related(
            "class_level__klass"
        )
        items += [
            {
                "name": _badged_heading(feature.name, _self_translated(feature, "name")),
                "detail": _("Feature of %(klass)s (Level %(level)s)")
                % {
                    "klass": feature.class_level.klass.name,
                    "level": feature.class_level.level,
                },
                "url": (
                    f"{reverse('world-class-detail', args=[feature.class_level.klass_id])}"
                    f"?tab=levels#feature-{feature.pk}"
                ),
            }
            for feature in features
        ]
    return _list_page(
        request,
        "Classes",
        items,
        world_tabs=True,
        search_query=q,
        search_placeholder=_("Search classes, subclasses and features"),
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
                            # The Features by Level cards this links to live on the Levels tab,
                            # not this (About) page, so the link needs that tab's own URL, not
                            # just a same-page `#feature-{pk}` fragment.
                            {"name": f.name, "href": f"?tab=levels#feature-{f.pk}"}
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
    category_filter = _pill_filter(
        request,
        "category",
        _("Category"),
        [(c, _format_feat_category(c)) for c in feat_service.list_categories()],
        all_label=_("All categories"),
    )
    feats = feat_service.list_feats()
    if q:
        feats = _by_name(feats, q)
    if category_filter["value"]:
        feats = feat_service.matching_category(feats, category_filter["value"])
    items = [
        {
            "pk": f.pk,
            "name": _badged_heading(f.name, _self_translated(f, "name")),
            "detail": _format_feat_category(f.category),
            "url": reverse("world-feat-detail", args=[f.pk]),
            # "Fighting Style (P)"/"(R)" sub-variants share their base category's artwork.
            "image": _menu_image_url(
                "feats", f"{f.category.split(' (')[0].lower().replace(' ', '_')}.jpeg"
            ),
        }
        for f in feats
    ]
    return _list_page(
        request,
        "Feats",
        items,
        world_tabs=True,
        compact_thumbs=True,
        search_query=q,
        search_placeholder=_("Search feats"),
        filters=[category_filter],
        bookmark_kind="feat",
    )


def world_feat_detail(request, pk):
    feat = feat_service.get_feat(pk)

    facts = [(_("Category"), _format_feat_category(feat.category))]
    if feat.prerequisite:
        facts.append((_("Prerequisite"), _format_prerequisite(feat.prerequisite)))
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


def world_species(request):
    q = _search_query(request)
    species_qs = species_service.list_species()
    if q:
        species_qs = _by_name(species_qs, q)
    items = [
        {
            "pk": s.pk,
            "name": _badged_heading(s.name, _self_translated(s, "name")),
            "detail": s.short_description,
            "url": reverse("world-species-detail", args=[s.pk]),
            "image": _menu_image_url("species", f"{_SPECIES_IMAGE_SLUGS.get(s.id, s.id)}-grey.png"),
        }
        for s in species_qs
    ]
    if q:
        traits = _by_name(Feature.objects.filter(species__isnull=False), q).select_related(
            "species"
        )
        items += [
            {
                "name": _badged_heading(trait.name, _self_translated(trait, "name")),
                "detail": _("Trait of %(species)s") % {"species": trait.species.name},
                "url": f"{reverse('world-species-detail', args=[trait.species_id])}?tab=traits",
            }
            for trait in traits
        ]
    return _list_page(
        request,
        "Species",
        items,
        world_tabs=True,
        search_query=q,
        search_placeholder=_("Search species and traits"),
        bookmark_kind="species",
    )


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
            (_("Speed"), units.distance(species.speed)),
            (_("Creature Type"), _format_creature_types(species.creature_types)),
        ]
        if species.darkvision:
            facts.append((_("Darkvision"), units.distance(species.darkvision)))
        facts.append((_("Page"), species.page))

        if species.lore:
            heading = _badged_heading(_("Lore"), _self_translated(species, "lore"))
            plain_sections.append((heading, render_entries(species.lore)))

    elif active_tab == "traits":
        if species.entries:
            body = render_trait_cards(
                species.entries, self_translated=_self_translated(species, "entries")
            )

    return _detail_page(
        request,
        _badged_heading(species.name, _self_translated(species, "name")),
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
