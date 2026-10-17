"""Export a finished character into the official D&D 5.5e character sheet PDF.

`pdf/character_sheet_template.pdf` is the official fillable sheet (two pages: the character, then
the spellcasting page). `export_pdf` computes the same numbers the web sheet shows (reusing
`character_sheet`'s helpers, so the PDF is in the reader's language and cannot drift from the
page) and writes them into the template's form fields.

The template's field names are mostly generic (`Text Box 14`, `Numeric Field 5`...), so the tables
below say which one is which; the spell grid is found by its position instead (see `_spell_grid`).
Fields are filled with `pypdf`; it cannot wrap or shrink text, so `_fit` does that by hand with
the template font's own glyph widths.
"""

import html
from io import BytesIO
from pathlib import Path

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.defaultfilters import slugify
from django.utils.html import strip_tags
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

from apps.builder.services import derived_stats
from apps.characters.models import Character
from apps.characters.services import access
from apps.frontend import character_sheet as sheet
from apps.frontend import units
from apps.frontend.character_views import _DAMAGE_TYPE_LABELS
from apps.frontend.views import (
    _format_casting_time,
    _format_range,
    _pick_translation,
)
from apps.rules.models import Equipment, Mastery

TEMPLATE = Path(__file__).parent / "pdf" / "character_sheet_template.pdf"

# --- which template field is which -------------------------------------------------------------

#: Per ability: the modifier (in the big circle), the score, the saving throw's value and tick.
_ABILITY_FIELDS = {
    "str": ("Strength Mod", "Numeric Field 3", "Text Box 13", "Check Box 8"),
    "dex": ("Text Box 15", "Numeric Field 4", "Text Box 16", "Check Box 13"),
    "con": ("Text Box 27", "Numeric Field 6", "Text Box 28", "Check Box 23"),
    "int": ("Text Box 6", "Numeric Field 2", "Text Box 7", "Int Saving Throw Proficiency"),
    "wis": ("Text Box 20", "Numeric Field 5", "Text Box 21", "Check Box 20"),
    "cha": ("Text Box 29", "Numeric Field 7", "Text Box 30", "Check Box 24"),
}
#: Per skill id: the bonus field and its proficiency tick.
_SKILL_FIELDS = {
    "athletics": ("Text Box 14", "Check Box 9"),
    "acrobatics": ("Text Box 17", "Check Box 14"),
    "sleight-of-hand": ("Text Box 18", "Check Box 15"),
    "stealth": ("Text Box 19", "Check Box 16"),
    "arcana": ("Text Box 8", "Arcana Proficiency"),
    "history": ("Text Box 9", "History Proficiency"),
    "investigation": ("Text Box 12", "Investigation Proficiency"),
    "nature": ("Text Box 10", "Nature Proficiency"),
    "religion": ("Text Box 11", "Religion Proficiency"),
    "animal-handling": ("Text Box 22", "Check Box 21"),
    "insight": ("Text Box 23", "Check Box 19"),
    "medicine": ("Text Box 25", "Check Box 18"),
    "perception": ("Text Box 24", "Check Box 22"),
    "survival": ("Text Box 26", "Check Box 17"),
    "deception": ("Text Box 32", "Check Box 28"),
    "intimidation": ("Text Box 33", "Check Box 25"),
    "performance": ("Text Box 34", "Check Box 26"),
    "persuasion": ("Text Box 31", "Check Box 27"),
}
#: The weapons table's rows, top to bottom: name, attack bonus, damage, notes.
_WEAPON_ROWS = (
    ("Text Box 35", "Text Box 53", "Text Box 47", "Text Box 41"),
    ("Text Box 36", "Text Box 54", "Text Box 51", "Text Box 42"),
    ("Text Box 37", "Text Box 55", "Text Box 52", "Text Box 43"),
    ("Text Box 38", "Text Box 56", "Text Box 48", "Text Box 44"),
    ("Text Box 39", "Text Box 57", "Text Box 49", "Text Box 45"),
    ("Text Box 40", "Text Box 58", "Text Box 50", "Text Box 46"),
)
_DEATH_SUCCESS_BOXES = ("Check Box 5", "Check Box 6", "Check Box 7")
_DEATH_FAILURE_BOXES = ("Check Box 2", "Check Box 3", "Check Box 4")
#: Armor training ticks: light, medium, heavy, shields (medium is two stacked widgets).
_ARMOR_BOXES = {
    "light": ("Check Box 12",),
    "medium": ("Check Box 11", "Medium Armor"),
    "heavy": ("Check Box 1",),
    "shield": ("Check Box 10",),
}
#: The "expended" boxes of each spell level on page 2.
_SLOT_BOXES = {
    1: ("Spell Slot 1.0", "Spell Slot 1.1", "Spell Slot 1.2", "Spell Slot 1.3"),
    2: ("Spell Slot 2.0", "Spell Slot 2.1", "Spell Slot 2.2"),
    3: ("Spell Slot 3.0", "Spell Slot 3.1", "Spell Slot 3.2"),
    4: ("Spell Slot 4.0", "Spell Slot 4.1", "Spell Slot 4.2"),
    5: ("Spell Slot 5.0", "Spell Slot 5.1", "Spell Slot 5.2"),
    6: ("Spell Slot 6.0", "Spell Slot 6.1"),
    7: ("Spell Slot 7.0", "Spell Slot 7.1"),
    8: ("Spell Slot 8",),
    9: ("Spell Slot 9",),
}
#: The slot totals, as a 3x3 grid: `Spell Level.<row>.<column>`; column 0 holds levels 1-3.
_SLOT_TOTALS = {
    row + column * 3 + 1: f"Spell Level.{row}.{column}" for row in range(3) for column in range(3)
}
_COIN_FIELDS = ("Coinage.0", "Coinage.1", "Coinage.2", "Coinage.3", "Coinage.4")  # CP SP EP GP PP
#: The three magic item lines (their attunement ticks are left for the player to mark).
_MAGIC_ITEMS = ("Text6", "Text7", "Text8")
_SPELL_ROWS = 30

_DEFAULT_SIZE = 8
_MIN_SIZE = 4.5


def _signed(value: int) -> str:
    return f"{value:+d}"


# --- the template ------------------------------------------------------------------------------


def _field_name(annotation) -> str:
    """The widget's fully qualified field name (`Spell Name.4.0`)."""
    parts = []
    node = annotation
    while node is not None:
        node = node.get_object()
        if "/T" in node:
            parts.append(str(node["/T"]))
        node = node.get("/Parent")
    return ".".join(reversed(parts))


def _field_type(widget) -> str | None:
    node = widget
    while node is not None:
        node = node.get_object()
        if "/FT" in node:
            return str(node["/FT"])
        node = node.get("/Parent")
    return None


def _widgets(
    writer: PdfWriter,
) -> list[list[tuple[str, object, tuple[float, float, float, float]]]]:
    """Per page: `(name, widget, (left, bottom, right, top))` of every form widget. The template
    stores some rectangles as indirect objects, which `pypdf` cannot build appearances from, so
    they are rewritten as plain numbers here."""
    pages = []
    for page in writer.pages:
        found = []
        for ref in page.get("/Annots", []):
            widget = ref.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            rect = tuple(float(x) for x in widget["/Rect"])
            widget[NameObject("/Rect")] = ArrayObject(FloatObject(x) for x in rect)
            found.append((_field_name(widget), widget, rect))
        pages.append(found)
    return pages


def _use_only_page_fields(writer: PdfWriter) -> None:
    """Point the form's field list at the fields the pages really draw. The template's list also
    holds leftover duplicates of many names (with their placeholder text), which a viewer reading
    the list instead of the pages would show instead of what was written."""
    roots: dict[int, object] = {}
    for page in writer.pages:
        for ref in page.get("/Annots", []):
            node = ref
            while "/Parent" in node.get_object():
                node = node.get_object().raw_get("/Parent")
            roots.setdefault(node.idnum, node)
    writer._root_object["/AcroForm"][NameObject("/Fields")] = ArrayObject(roots.values())


def _drop_source_file(writer: PdfWriter) -> None:
    """The template carries its LibreOffice source (5.7 MB of the 14 MB) as an attachment: drop
    it, and everything that then has nothing pointing to it, from the copy a player downloads."""
    root = writer._root_object
    attachments = root["/Names"]["/EmbeddedFiles"]
    for item in attachments.get("/Names", []):
        spec = item.get_object()
        if hasattr(spec, "keys") and "/EF" in spec:
            del spec["/EF"]
    del root["/Names"]["/EmbeddedFiles"]
    root.pop("/AF", None)


def _spell_grid(widgets) -> list[dict[str, str]]:
    """Page 2's spell table as rows, top to bottom: `{level, name, time, c, r, m, notes}` field
    names. The template numbers them in no reliable order, so they are sorted by position."""
    columns = {
        "level": "Spell's Level.",
        "name": "Spell Name.",
        "time": "Spell Casting Time.",
        "notes": "Spell Notes.",
        "c": "Check Box.0.0.",
        "r": "Check Box.0.1.",
        "m": "Check Box.0.2.",
    }
    rows: list[dict[str, str]] = [{} for _row in range(_SPELL_ROWS)]
    for key, prefix in columns.items():
        # PDF y runs upwards, so the top row has the largest top edge.
        ordered = sorted(
            (rect for name, _w, rect in widgets if name.startswith(prefix)), key=lambda r: -r[3]
        )
        names = {rect: name for name, _w, rect in widgets if name.startswith(prefix)}
        for row, rect in zip(rows, ordered, strict=True):
            row[key] = names[rect]
    return rows


# --- fitting text into a field -------------------------------------------------------------------


class _Font:
    """Glyph widths of the template's own font, to measure text without rendering it."""

    def __init__(self, writer: PdfWriter):
        font = writer._root_object["/AcroForm"]["/DR"]["/Font"]["/Immortal"].get_object()
        self.first = int(font["/FirstChar"])
        self.widths = [float(w) for w in font["/Widths"]]

    def width(self, text: str, size: float) -> float:
        total = 0.0
        for char in text.encode("cp1252", "replace"):
            index = char - self.first
            total += self.widths[index] if 0 <= index < len(self.widths) else 500
        return total * size / 1000

    def wrap(self, text: str, size: float, width: float) -> list[str]:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split(" "):
                trial = f"{line} {word}" if line else word
                if line and self.width(trial, size) > width:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            lines.append(line)
        return lines


def _clean(text: str) -> str:
    """Only what the template font (Windows-1252) can show."""
    return text.encode("cp1252", "replace").decode("cp1252")


def _fit(font: _Font, widget, rect, text: str) -> str:
    """The text as it should be stored in `widget`: a single line is shrunk until it fits, a
    multi-line field is wrapped and shrunk until all of it fits (cut off, with "...", only when
    even the smallest size is not enough). The font size is set on the widget."""
    text = _clean(text)
    width = rect[2] - rect[0] - 4
    height = rect[3] - rect[1] - 4
    multiline = bool(int(widget.get("/Ff", 0)) & 4096)
    declared = 0.0
    parts = str(widget.get("/DA", "")).split()
    if "Tf" in parts and parts.index("Tf") >= 1:
        declared = float(parts[parts.index("Tf") - 1])
    size = declared or _DEFAULT_SIZE
    if not multiline:
        text = text.replace("\n", " ")
        while size > _MIN_SIZE and font.width(text, size) > width:
            size -= 0.5
    else:
        while True:
            lines = font.wrap(text, size, width)
            if len(lines) * size * 1.2 <= height or size <= _MIN_SIZE:
                break
            size -= 0.5
        room = max(1, int(height / (size * 1.2)))
        if len(lines) > room:
            lines = lines[:room]
            lines[-1] = lines[-1].rstrip() + " ..."
        text = "\n".join(lines)
    widget[NameObject("/DA")] = TextStringObject(f"/Immortal {size:g} Tf 0 g")
    return text


# --- what to write -------------------------------------------------------------------------------


def _plain(markup) -> str:
    return html.unescape(strip_tags(str(markup)))


def _damage(attack: dict) -> str:
    kind = (
        _pick_translation(_DAMAGE_TYPE_LABELS, attack["damage_type"])
        if attack["damage_type"]
        else ""
    )
    text = f"{attack['damage']} {kind}".strip()
    if attack["damage_two_handed"]:  # Versatile: the bigger die with both hands on it
        text += f" ({attack['damage_two_handed']} {_('two-handed')})"
    return text


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _page_one(character: Character, stats, classes) -> tuple[dict[str, str], set[str]]:
    text: dict[str, str] = {}
    ticks: set[str] = set()
    identity = sheet._identity(character, classes)
    strip = sheet._strip(
        character, stats, list(character.inventory_items.select_related("equipment"))
    )
    proficiencies = sheet._proficiencies(character)

    text["Text Box 1"] = character.name
    text["Text Box 2"] = character.background.name if character.background else ""
    text["Text Box 3"] = " / ".join(c["name"] for c in identity["classes"])
    text["Text Box 4"] = character.species.name if character.species else ""
    text["Text Box 5"] = " / ".join(c["subclass"] for c in identity["classes"] if c["subclass"])
    text["Level"] = str(stats.level)
    text["XP"] = str(character.experience_points)

    text["AC"] = str(stats.armor_class["value"])
    if stats.armor_class["shield"]:
        ticks.add("Option Button 1")
    text["Current HP"] = str(character.current_hit_points)
    text["Temp HP"] = str(character.temporary_hit_points)
    text["Max HP"] = str(character.hit_point_maximum)
    dice = stats.hit_dice
    text["Hit Dice Spent"] = str(sum(d["spent"] for d in dice.values()))
    text["Hit Dice Max"] = "+".join(f"{d['total']}{die}" for die, d in dice.items())
    ticks.update(_DEATH_SUCCESS_BOXES[: character.death_save_successes])
    ticks.update(_DEATH_FAILURE_BOXES[: character.death_save_failures])
    if character.inspiration:
        ticks.add("Inspiration")

    text["Text Box 59"] = _signed(stats.initiative)  # Initiative
    text["Speed"] = units.distance(stats.speed)
    text["Size Field"] = identity["size"]
    text["Passive Perception"] = str(stats.passive_perception)
    text["Prof Bonus"] = _signed(stats.proficiency_bonus)

    for ability, (mod, score, save, save_tick) in _ABILITY_FIELDS.items():
        text[mod] = _signed(stats.abilities[ability]["modifier"])
        text[score] = str(stats.abilities[ability]["score"])
        text[save] = _signed(stats.saving_throws[ability]["modifier"])
        if stats.saving_throws[ability]["proficient"]:
            ticks.add(save_tick)
    for skill, (field, tick) in _SKILL_FIELDS.items():
        text[field] = _signed(stats.skills[skill]["modifier"])
        if stats.skills[skill]["state"] != "none":
            ticks.add(tick)

    # Armor training, weapon and tool proficiencies.
    held = {(p.category, p.name) for p in character.proficiencies.all()}
    for category, boxes in _ARMOR_BOXES.items():
        if ("armor", category) in held:
            ticks.update(boxes)
    weapon_lines = [group["title"] for group in proficiencies["weapons"]]
    if proficiencies["masteries"]:
        weapon_lines.append(
            f"{_('Weapon Masteries')}: "
            + ", ".join(f"{m['name']} ({m['detail']})" for m in proficiencies["masteries"])
        )
    text["Weapon Profs"] = "\n".join(weapon_lines)
    text["Tool Profs"] = ", ".join(
        chip["name"] for group in proficiencies["tool_groups"] for chip in group["chips"]
    )

    # Weapons & damage: the attacks the character can make with what it carries.
    names = {
        e.id: e.name
        for e in Equipment.objects.filter(id__in=[a["equipment_id"] for a in stats.attacks])
    }
    mastery_names = {m.id: m.name for m in Mastery.objects.all()}
    for attack, (name, bonus, damage, notes) in zip(stats.attacks, _WEAPON_ROWS, strict=False):
        text[name] = attack["custom_name"] or names.get(
            attack["equipment_id"], attack["equipment_id"]
        )
        text[bonus] = _signed(attack["attack_bonus"])
        text[damage] = _damage(attack)
        text[notes] = ", ".join(mastery_names.get(m, m) for m in attack["masteries"])

    # Features, traits and feats: names only - their text lives on the web sheet.
    features = sheet._feature_items(character)
    by_type: dict[str, list[str]] = {}
    for item in features:
        by_type.setdefault(item["type"], []).append(item["name"])
    resources = [f"{r['name']}: {r['current']}/{r['max']}" for r in strip["resources"]]
    # A sense usually is a species trait too ("Darkvision"): show the trait with its range.
    traits = by_type.get("species", [])
    for held in character.senses.select_related("sense"):
        label = f"{held.sense.name} {units.distance(held.range_feet)}".strip()
        if held.sense.name in traits:
            traits[traits.index(held.sense.name)] = label
        else:
            traits.append(label)
    text["Class Features 1"] = _bullets(by_type.get("class", []))
    text["Class Features 2"] = _bullets(
        by_type.get("subclass", []) + by_type.get("option", []) + resources
    )
    text["Species Traits"] = _bullets(traits)
    text["Feats"] = _bullets(by_type.get("feat", []))
    return text, ticks


def _page_two(character: Character, stats, classes) -> tuple[dict[str, str], set[str], list]:
    text: dict[str, str] = {}
    ticks: set[str] = set()
    biography = sheet._biography(character)
    inventory = sheet._inventory(character, stats)
    spellbook = sheet._spellbook_rows(character, can_edit=False)
    sources = sheet._casting_sources(stats, classes)
    slots = sheet._slots(character, stats, classes)

    # Spellcasting ability: the first class source (a species or feat one only if there is none).
    source = next(
        (s for s in sources if s["id"].startswith("class:")), sources[0] if sources else None
    )
    if source:
        text["Spellcasting.0"] = _signed(source["modifier"])
        text["Spellcasting.1"] = str(source["dc"])
        text["Spellcasting.2"] = _signed(source["attack"])

    # Slot pools of the same level (a Pact Magic pool next to a multiclass table) share a row.
    totals: dict[int, list[int]] = {}
    for pool in slots:
        total = totals.setdefault(pool["level"], [0, 0])
        total[0] += pool["max"]
        total[1] += pool["spent"]
    for level, (maximum, spent) in totals.items():
        if level in _SLOT_TOTALS:
            text[_SLOT_TOTALS[level]] = str(maximum)
            ticks.update(_SLOT_BOXES[level][:spent])

    text["Text2"] = character.appearance
    story = [biography["backstory"], character.notes]
    text["Text1"] = "\n\n".join(part.strip() for part in story if part.strip())
    text["Text3"] = biography["alignment"]
    text["Text4"] = ", ".join(
        sorted(cl.language.name for cl in character.languages.select_related("language"))
    )

    lines = []
    for section in inventory["sections"]:
        for card in section["cards"]:
            line = f"{card['quantity']}x " if card["quantity"] > 1 else ""
            line += card["name"]
            if card["equipped"]:
                line += f" ({_('Equipped').lower()})"
            lines.append(line)
    text["Text5"] = "\n".join(lines)
    attunable = character.inventory_items.exclude(equipment__attunement="").select_related(
        "equipment"
    )
    for field, row in zip(_MAGIC_ITEMS, attunable, strict=False):
        text[field] = row.equipment.name

    purse = {coin["key"]: coin["amount"] for coin in inventory["coins"]}
    for field, key in zip(
        _COIN_FIELDS, ("copper", "silver", "electrum", "gold", "platinum"), strict=True
    ):
        text[field] = str(purse.get(key, 0))
    return text, ticks, spellbook


def _spell_priority(row: dict) -> tuple:
    """Cantrips and prepared spells first when there are more spells than the sheet has rows."""
    spell = row["spell"]
    ready = (
        spell.level == 0 or _("Prepared") in row["detail"] or _("Always prepared") in row["detail"]
    )
    return (not ready, spell.level, spell.name)


def _spell_rows(spellbook: list[dict]) -> list[dict]:
    rows = sorted(spellbook, key=lambda r: (r["level"], r["spell"].name))
    if len(rows) > _SPELL_ROWS:
        rows = sorted(
            sorted(rows, key=_spell_priority)[:_SPELL_ROWS],
            key=lambda r: (r["level"], r["spell"].name),
        )
    return rows


def _spell_values(grid: list[dict[str, str]], spellbook: list[dict]) -> tuple[dict, set]:
    text: dict[str, str] = {}
    ticks: set[str] = set()
    for fields, row in zip(grid, _spell_rows(spellbook), strict=False):
        spell = row["spell"]
        components = spell.components or {}
        letters = [k.upper() for k in ("v", "s", "m") if components.get(k)]
        text[fields["level"]] = str(spell.level)
        text[fields["name"]] = spell.name
        text[fields["time"]] = _plain(_format_casting_time(spell.casting_time))
        text[fields["notes"]] = " · ".join(
            part for part in (_format_range(spell.range), ",".join(letters)) if part
        )
        if spell.concentration:
            ticks.add(fields["c"])
        if spell.ritual:
            ticks.add(fields["r"])
        if components.get("m"):
            ticks.add(fields["m"])
    return text, ticks


# --- writing it ----------------------------------------------------------------------------------


def export_pdf(character: Character) -> bytes:
    """The character as a filled-in copy of the official sheet."""
    stats = derived_stats.compute(character)
    classes = list(character.classes.select_related("klass", "subclass"))
    writer = PdfWriter(clone_from=TEMPLATE)
    font = _Font(writer)
    pages = _widgets(writer)
    _use_only_page_fields(writer)
    _drop_source_file(writer)

    text_one, ticks_one = _page_one(character, stats, classes)
    text_two, ticks_two, spellbook = _page_two(character, stats, classes)
    grid = _spell_grid(pages[1])
    spell_text, spell_ticks = _spell_values(grid, spellbook)
    text_two.update(spell_text)
    ticks_two |= spell_ticks

    for page, found, text, ticks in (
        (writer.pages[0], pages[0], text_one, ticks_one),
        (writer.pages[1], pages[1], text_two, ticks_two),
    ):
        values: dict[str, str] = {}
        for name, widget, rect in found:
            kind = _field_type(widget)
            if kind == "/Tx":
                # Every text field is written, so none keeps the template's "Spell Name" etc.
                values[name] = _fit(font, widget, rect, text.get(name, ""))
            elif kind == "/Btn":
                values[name] = "/Yes" if name in ticks else "/Off"
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
    writer.set_need_appearances_writer(True)  # viewers redraw the fields with their own fonts

    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@require_GET
def character_export_pdf(request, pk):
    character = get_object_or_404(
        Character.objects.select_related("species", "background", "owner"), pk=pk
    )
    if not access.can_view(request.user, character) or character.status == Character.STATUS_DRAFT:
        raise Http404
    response = HttpResponse(export_pdf(character), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{slugify(character.name) or "character"}.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    return response
