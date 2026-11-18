"""What levelling up gives and asks for, at the levels where `db/` only says it in prose.

`rules` has the numbers (`ClassLevel`: spell slots, cantrips, prepared spells, the class table's
columns; `Feature` rows per level) but not *when a class asks the player to choose something* or
what a multiclass entry grants - those are English sentences in `Feature.entries` and the SRD's
"Multiclassing" rules. Like `class_spec.py` (level 1), the rules of the choices are stated once
here. Ids are `rules` ids. Built from the SRD 5.2 text; `tests/test_progression.py` checks the
table against the imported data (each level named here really has its feature).
"""

from dataclasses import dataclass

MAX_LEVEL = 20
#: The score a feat / Ability Score Improvement cannot push past: 20, or 30 for an Epic Boon.
ABILITY_CAP = 20
EPIC_BOON_CAP = 30
#: A multiclass character needs this score in the primary ability of the new class *and* of every
#: class they already have (SRD "Multiclassing").
MULTICLASS_MINIMUM = 13

#: Feature names that are not something the character "has" but a marker the level-up turns into
#: a choice: a feat, the subclass pick, or a subclass's placeholder row in the class table.
ASI_FEATURES = ("Ability Score Improvement", "Epic Boon")
SUBCLASS_MARKER = "Subclass Feature"
#: Level-up feature rows that are reference tables of options (picked from, not had).
REFERENCE_FEATURES = {
    "Eldritch Invocation Options",
    "Metamagic Options",
    "Maneuver Options",
    "Maneuvers Options",
}


@dataclass(frozen=True)
class MulticlassGain:
    """What entering a class as a *second* class grants (SRD "Multiclass Proficiencies")."""

    armor: tuple[str, ...] = ()
    weapons: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()  # equipment ids
    skills: int = 0  # skills to pick...
    skill_list: tuple[str, ...] = ()  # ...from this list (empty: any skill)
    instrument: bool = False  # one musical instrument of choice


_RANGER_SKILLS = (
    "animal-handling",
    "athletics",
    "insight",
    "investigation",
    "nature",
    "perception",
    "stealth",
    "survival",
)
_ROGUE_SKILLS = (
    "acrobatics",
    "athletics",
    "deception",
    "insight",
    "intimidation",
    "investigation",
    "perception",
    "persuasion",
    "sleight-of-hand",
    "stealth",
)
MULTICLASS_GAINS: dict[str, MulticlassGain] = {
    "barbarian": MulticlassGain(armor=("shield",), weapons=("martial",)),
    "bard": MulticlassGain(armor=("light",), skills=1, instrument=True),
    "cleric": MulticlassGain(armor=("light", "medium", "shield")),
    "druid": MulticlassGain(armor=("light", "shield")),
    "fighter": MulticlassGain(armor=("light", "medium", "shield"), weapons=("martial",)),
    "monk": MulticlassGain(),
    "paladin": MulticlassGain(armor=("light", "medium", "shield"), weapons=("martial",)),
    "ranger": MulticlassGain(
        armor=("light", "medium", "shield"),
        weapons=("martial",),
        skills=1,
        skill_list=_RANGER_SKILLS,
    ),
    "rogue": MulticlassGain(
        armor=("light",), tools=("thieves-tools",), skills=1, skill_list=_ROGUE_SKILLS
    ),
    "sorcerer": MulticlassGain(),
    "warlock": MulticlassGain(armor=("light",)),
    "wizard": MulticlassGain(),
}

# --- class-level choices ---------------------------------------------------------------------

#: `{class: {class level: number of skills to gain Expertise in}}`.
EXPERTISE_AT = {"rogue": {6: 2}, "bard": {2: 2, 9: 2}, "ranger": {9: 2}}
#: Classes that pick a Fighting Style feat at that class level (Fighter does at level 1).
FIGHTING_STYLE_AT = {"paladin": 2, "ranger": 2}
#: Feat category ids offered besides the general "Fighting Style" ones.
CLASS_FIGHTING_STYLE_CATEGORY = {"paladin": "Fighting Style (P)", "ranger": "Fighting Style (R)"}
#: A subclass that asks for one more Fighting Style at that class level (Champion).
SUBCLASS_FIGHTING_STYLE_AT = {("fighter", "Champion"): 7}
#: One-off choices at one class level: Barbarian 3 (Primal Knowledge), Wizard 2 (Scholar), Ranger 2.
BARBARIAN_PRIMAL_KNOWLEDGE = ("barbarian", 3)
BARBARIAN_SKILLS = (
    "animal-handling",
    "athletics",
    "intimidation",
    "nature",
    "perception",
    "stealth",
    "survival",
)
WIZARD_SCHOLAR = ("wizard", 2)
WIZARD_SCHOLAR_SKILLS = ("arcana", "history", "investigation", "medicine", "nature", "religion")
RANGER_DEFT_EXPLORER = ("ranger", 2)
#: Subclass one-offs: `{(class, subclass name): [(level, kind, count)]}` - `skills` any skills,
#: `tool` one artisan's tool, `fighter_skill` a skill from the Fighter's list.
SUBCLASS_PICKS = {
    ("bard", "College of Lore"): {3: [("skills", 3)]},
    ("fighter", "Battle Master"): {3: [("artisan_tool", 1), ("fighter_skill", 1)]},
}
FIGHTER_SKILLS = (
    "acrobatics",
    "animal-handling",
    "athletics",
    "history",
    "insight",
    "intimidation",
    "persuasion",
    "perception",
    "survival",
)
#: Proficiencies a subclass hands over outright at that class level.
SUBCLASS_GRANTS = {
    ("bard", "College of Valor"): {3: {"weapons": ("martial",), "armor": ("medium", "shield")}},
    ("monk", "Warrior of Mercy"): {
        3: {"skills": ("insight", "medicine"), "tools": ("herbalism-kit",)}
    },
    ("rogue", "Assassin"): {3: {"tools": ("disguise-kit", "poisoners-kit")}},
}

#: Battle Master maneuvers known, by Fighter level - and Superiority Dice / their size.
MANEUVERS_KNOWN = {3: 3, 7: 5, 10: 7, 15: 9}
#: Sorcerer Metamagic options known.
METAMAGIC_KNOWN = {2: 2, 10: 4, 17: 6}
#: Warlock Mystic Arcanum: class level -> the level of the spell chosen.
MYSTIC_ARCANUM_AT = {11: 6, 13: 7, 15: 8, 17: 9}
#: Classes whose known/prepared spells may be swapped for another each time they gain a level
#: (the others change their prepared list on a Long Rest, which the sheet lets the player do).
SWAP_SPELL_CLASSES = ("bard", "sorcerer", "ranger", "warlock")
#: A subclass that grants a fixed cantrip but, if it is already known, lets the player learn a
#: different one instead: `{(class, subclass name): (cantrip id, spell list)}` (Improved Illusions).
SUBCLASS_DUPLICATE_CANTRIP = {("wizard", "Illusionist"): ("minor-illusion", "Wizard")}
#: Bard Magical Secrets (class level 10): new prepared spells may come from these lists too.
MAGICAL_SECRETS_FROM = 10
MAGICAL_SECRETS_LISTS = ("Cleric", "Druid", "Wizard")
#: Wizard Spell Mastery / Signature Spells: the class levels that choose from the spellbook.
SPELL_MASTERY_AT = 18
SIGNATURE_SPELLS_AT = 20
#: Wizard: spells copied into the spellbook each level, and at level 1 (or on entering the class).
WIZARD_SPELLBOOK_PER_LEVEL = 2
WIZARD_SPELLBOOK_START = 6

# --- hit points ------------------------------------------------------------------------------

#: Features (by name) that add hit points per level, and how many: Tough is a feat (2 a level),
#: the others are features.
HP_PER_LEVEL_FEATS = {"tough": 2}
HP_PER_LEVEL_FEATURES = {"Dwarven Toughness": 1}
#: Draconic Sorcery: +3 hit points when taken (at level 3), then +1 per Sorcerer level.
HP_PER_CLASS_LEVEL_SUBCLASS = {("sorcerer", "Draconic Sorcery"): 1}

# --- resources -------------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelResource:
    """A limited-use resource whose maximum follows the class level.

    `maximum`: `("column", header)` from the class table; `("by_level", {level: n})` the value
    of the highest level reached; `("per_level", n)`; `("mod", ability)` a modifier (at least 1);
    `("proficiency", None)`. `reset_on` as in `CharacterResource` ("other" = one back on a short
    rest, all on a long rest). `from_level` is the class level it first exists at (`subclass`:
    only with that subclass).
    """

    name: str
    maximum: tuple
    reset_on: str
    from_level: int = 1
    subclass: str = ""


_LONG, _SHORT, _OTHER = "long_rest", "short_rest", "other"
LEVEL_RESOURCES: dict[str, tuple[LevelResource, ...]] = {
    "barbarian": (LevelResource("Rage", ("column", "Rages"), _OTHER),),
    "bard": (
        LevelResource("Bardic Inspiration", ("mod", "cha"), _LONG),
        LevelResource("Bardic Inspiration", ("mod", "cha"), _SHORT, from_level=5),
    ),
    "cleric": (
        LevelResource("Channel Divinity", ("column", "Channel Divinity"), _OTHER, from_level=2),
        LevelResource("Divine Intervention", ("by_level", {10: 1}), _LONG, from_level=10),
    ),
    "druid": (LevelResource("Wild Shape", ("column", "Wild Shape"), _OTHER, from_level=2),),
    "fighter": (
        LevelResource("Second Wind", ("column", "Second Wind"), _OTHER),
        LevelResource("Action Surge", ("by_level", {2: 1, 17: 2}), _SHORT, from_level=2),
        LevelResource("Indomitable", ("by_level", {9: 1, 13: 2, 17: 3}), _LONG, from_level=9),
        LevelResource(
            "Superiority Dice",
            ("by_level", {3: 4, 7: 5, 15: 6}),
            _SHORT,
            from_level=3,
            subclass="Battle Master",
        ),
    ),
    "monk": (
        LevelResource("Focus Points", ("column", "Focus Points"), _SHORT, from_level=2),
        LevelResource("Uncanny Metabolism", ("by_level", {2: 1}), _LONG, from_level=2),
    ),
    "paladin": (
        LevelResource("Lay on Hands", ("per_level", 5), _LONG),
        LevelResource("Channel Divinity", ("column", "Channel Divinity"), _OTHER, from_level=3),
    ),
    "ranger": (
        LevelResource("Favored Enemy", ("column", "Favored Enemy"), _LONG),
        LevelResource("Tireless", ("proficiency", None), _LONG, from_level=10),
        LevelResource("Nature's Veil", ("proficiency", None), _LONG, from_level=14),
    ),
    "rogue": (LevelResource("Stroke of Luck", ("by_level", {20: 1}), _SHORT, from_level=20),),
    "sorcerer": (
        LevelResource("Innate Sorcery", ("by_level", {1: 2}), _LONG),
        LevelResource("Sorcery Points", ("column", "Sorcery Points"), _LONG, from_level=2),
    ),
    "warlock": (LevelResource("Magical Cunning", ("by_level", {2: 1}), _LONG, from_level=2),),
    "wizard": (LevelResource("Arcane Recovery", ("by_level", {1: 1}), _LONG),),
}

# --- subclass casters (Eldritch Knight, Arcane Trickster) -------------------------------------


@dataclass(frozen=True)
class SubclassCasting:
    """A third-caster subclass: Wizard-list spells, Intelligence, slots from the subclass's own
    table (which is not in `ClassLevel`). Rows are indexed by class level - 1."""

    ability: str
    cantrips: tuple[int, ...]
    prepared: tuple[int, ...]
    slots: tuple[tuple[int, ...], ...]  # per level: slots of spell level 1..4


_THIRD_PREPARED = (0, 0, 3, 4, 4, 4, 5, 6, 6, 7, 8, 8, 9, 10, 10, 11, 11, 11, 12, 13)
_THIRD_CANTRIPS = (0, 0, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3)
_THIRD_SLOTS = (
    (0, 0, 0, 0), (0, 0, 0, 0), (2, 0, 0, 0), (3, 0, 0, 0), (3, 0, 0, 0), (3, 0, 0, 0),
    (4, 2, 0, 0), (4, 2, 0, 0), (4, 2, 0, 0), (4, 3, 0, 0), (4, 3, 0, 0), (4, 3, 0, 0),
    (4, 3, 2, 0), (4, 3, 2, 0), (4, 3, 2, 0), (4, 3, 3, 0), (4, 3, 3, 0), (4, 3, 3, 0),
    (4, 3, 3, 1), (4, 3, 3, 1),
)  # fmt: skip
SUBCLASS_CASTING = {
    ("fighter", "Eldritch Knight"): SubclassCasting(
        "int", _THIRD_CANTRIPS, _THIRD_PREPARED, _THIRD_SLOTS
    ),
    ("rogue", "Arcane Trickster"): SubclassCasting(
        "int", _THIRD_CANTRIPS, _THIRD_PREPARED, _THIRD_SLOTS
    ),
}
#: The list a subclass caster draws spells from.
SUBCLASS_CASTING_LIST = "Wizard"
