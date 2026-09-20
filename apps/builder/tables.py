"""Static tables and formulas from the SRD's "Creazione del personaggio" chapter.

None of this exists in `db/` (the handbook there only covers chapter 1), and it is not modelled
as `rules` rows either: `import_rules_data` wipes every `rules` table and there is no source JSON
to reload them from. So they are plain constants here - pure Python, no database, no Django
models - which makes them trivially testable. `docs/character_creation_plan.md` section 3.3 lists
where each one comes from.

Ability ids are the ones `rules.Ability` uses (`str`, `dex`, `con`, `int`, `wis`, `cha`).
"""

from django.utils.translation import gettext_lazy as _

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")

#: `rules.Ability.id` -> the field of `characters.Character` holding that score.
ABILITY_FIELDS = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}

# --- Step 3: ability scores ------------------------------------------------------------------

STANDARD_ARRAY = (15, 14, 13, 12, 10, 8)

#: SRD "Serie standard per classe": how to assign the standard array for each class.
STANDARD_ARRAY_BY_CLASS = {
    "barbarian": {"str": 15, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8},
    "bard": {"str": 8, "dex": 14, "con": 12, "int": 13, "wis": 10, "cha": 15},
    "cleric": {"str": 14, "dex": 8, "con": 13, "int": 10, "wis": 15, "cha": 12},
    "druid": {"str": 8, "dex": 12, "con": 14, "int": 13, "wis": 15, "cha": 10},
    "fighter": {"str": 15, "dex": 14, "con": 13, "int": 8, "wis": 10, "cha": 12},
    "rogue": {"str": 12, "dex": 15, "con": 13, "int": 14, "wis": 10, "cha": 8},
    "wizard": {"str": 8, "dex": 12, "con": 13, "int": 15, "wis": 14, "cha": 10},
    "monk": {"str": 12, "dex": 15, "con": 13, "int": 10, "wis": 14, "cha": 8},
    "paladin": {"str": 15, "dex": 10, "con": 13, "int": 8, "wis": 12, "cha": 14},
    "ranger": {"str": 12, "dex": 15, "con": 13, "int": 8, "wis": 14, "cha": 10},
    "sorcerer": {"str": 10, "dex": 13, "con": 14, "int": 8, "wis": 12, "cha": 15},
    "warlock": {"str": 8, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 15},
}

POINT_BUY_BUDGET = 27
#: SRD "Costi in punti del punteggio di caratteristica" - the only scores point buy allows.
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}

#: A background raises one ability by 2 and another by 1, or three abilities by 1 each.
BACKGROUND_BONUS_SPREADS = ((2, 1), (1, 1, 1))
#: Nothing during creation may push a score above this (SRD "Modificare i punteggi").
CREATION_SCORE_CAP = 20
#: The manual override at the end of creation is deliberately looser than any rule.
MANUAL_SCORE_RANGE = (1, 30)


def ability_modifier(score: int) -> int:
    """SRD "Punteggi di caratteristica e modificatori": 3 -> -4, 8-9 -> -1, 10-11 -> 0, 20 -> +5."""
    return (score - 10) // 2


def point_buy_cost(scores: dict[str, int]) -> int:
    """Total point-buy cost of six scores; raises `ValueError` for a score outside 8-15."""
    try:
        return sum(POINT_BUY_COST[value] for value in scores.values())
    except KeyError as exc:
        raise ValueError(f"point buy only allows scores 8-15, got {exc.args[0]}") from exc


# --- Advancement -----------------------------------------------------------------------------

#: SRD "Avanzamento dei personaggi": total XP needed to *reach* each level (index = level - 1).
XP_BY_LEVEL = (
    0,
    300,
    900,
    2_700,
    6_500,
    14_000,
    23_000,
    34_000,
    48_000,
    64_000,
    85_000,
    100_000,
    120_000,
    140_000,
    165_000,
    195_000,
    225_000,
    265_000,
    305_000,
    355_000,
)


def proficiency_bonus(total_level: int) -> int:
    """+2 at levels 1-4, +3 at 5-8, ... +6 at 17-20 - matches every row of the SRD table."""
    return 2 + (total_level - 1) // 4


def xp_for_level(level: int) -> int:
    return XP_BY_LEVEL[level - 1]


def level_for_xp(xp: int) -> int:
    return sum(1 for threshold in XP_BY_LEVEL if xp >= threshold)


# --- Hit points ------------------------------------------------------------------------------


def hit_die_faces(hit_die: str) -> int:
    """`"d10"` -> 10 (the form `rules.Class.hit_die` stores)."""
    return int(hit_die.lstrip("d"))


def hp_first_level(hit_die: str, con_modifier: int) -> int:
    """SRD "Punti ferita per classe al 1º livello": the full die plus Constitution."""
    return hit_die_faces(hit_die) + con_modifier


def hp_fixed_per_level(hit_die: str, con_modifier: int) -> int:
    """SRD "Punti ferita fissi per classe": half the die, rounded up, plus Constitution.
    (d12 -> 7, d10 -> 6, d8 -> 5, d6 -> 4.)
    """
    return hit_die_faces(hit_die) // 2 + 1 + con_modifier


# --- Step 2: languages -----------------------------------------------------------------------

#: SRD "Lingue standard": 1d12 -> `rules.Language.id`. Common is automatic and not on the table.
LANGUAGE_D12 = {
    1: "common-sign-language",
    2: "draconic",
    3: "dwarvish",
    4: "dwarvish",
    5: "elvish",
    6: "elvish",
    7: "giant",
    8: "gnomish",
    9: "goblin",
    10: "halfling",
    11: "halfling",
    12: "orc",
}
STANDARD_LANGUAGE_IDS = tuple(dict.fromkeys(LANGUAGE_D12.values()))
COMMON_LANGUAGE_ID = "common"
#: Common plus this many more, chosen or rolled.
EXTRA_LANGUAGES_AT_CREATION = 2

# --- Step 4: alignment -----------------------------------------------------------------------

#: (code, name, abbreviation). Codes are language-neutral; the labels are translated
#: (Italian: Legale buono "LB", Legale malvagio "LM", ...).
ALIGNMENTS = (
    ("LG", _("Lawful Good"), _("LG")),
    ("NG", _("Neutral Good"), _("NG")),
    ("CG", _("Chaotic Good"), _("CG")),
    ("LN", _("Lawful Neutral"), _("LN")),
    ("N", _("Neutral"), _("N")),
    ("CN", _("Chaotic Neutral"), _("CN")),
    ("LE", _("Lawful Evil"), _("LE")),
    ("NE", _("Neutral Evil"), _("NE")),
    ("CE", _("Chaotic Evil"), _("CE")),
)
ALIGNMENT_CODES = tuple(code for code, _name, _abbr in ALIGNMENTS)
#: The SRD asks players to consult the GM before creating an evil character: a warning, no block.
EVIL_ALIGNMENT_CODES = ("LE", "NE", "CE")

# --- Armor -----------------------------------------------------------------------------------

#: Most Dexterity modifier that counts toward AC, by `rules.EquipmentType.id` (`None` = no cap).
#: Light armor: no cap; medium: 2; heavy: Dexterity does not count at all.
ARMOR_DEX_CAP = {"la": None, "ma": 2, "ha": 0}
SHIELD_TYPE_ID = "s"
