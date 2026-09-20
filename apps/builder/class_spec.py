"""What each class asks for at level 1 that `db/` only states in prose.

`rules` holds a class's numbers (hit die, saves, spell counts per level, resource counts in
`ClassLevel.columns`) but the *rules of the choices* - "pick 2 weapons for Weapon Mastery",
"Expertise in 2 of your skills", "a spellbook of 6" - are English sentences inside
`Feature.entries`. With twelve classes it is cheaper and safer to state them once, here, and have
tests (`apps/builder/tests/test_class_spec.py`) fail the moment the imported data stops agreeing
with this file. See `docs/character_creation_plan.md` section 3.4.

Only what creation at level 1 needs is here (D4: level 1 only, for now). Ids are `rules` ids:
class ids (`fighter`), ability ids (`str`), skill ids (`sleight-of-hand`), language ids, spell ids.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeaponMasterySpec:
    """`count` kinds of weapon whose Mastery property the character can use."""

    count: int
    #: Barbarian: "Simple or Martial *Melee* weapons" - `Equipment.type_id == "m"`. (The pool of
    #: weapons to pick from is type `m`/`r` with a category: the focus-typed "Staff"/"Wooden Staff"
    #: duplicate the Quarterstaff and are not offered.)
    melee_only: bool = False
    #: Paladin/Ranger/Rogue: "weapons of your choice with which you have proficiency".
    proficient_only: bool = False


@dataclass(frozen=True)
class OrderOption:
    """One alternative of Cleric's Divine Order / Druid's Primal Order. The *choice* is
    structured in `db/` (an `options` node), what each option grants is only prose."""

    feature: str  # `Feature.name` of the option, e.g. "Protector"
    weapon_categories: tuple[str, ...] = ()
    armor_categories: tuple[str, ...] = ()
    extra_cantrips: int = 0
    #: Skills that get a bonus equal to the Wisdom modifier (minimum +1) - Thaumaturge/Magician.
    wisdom_bonus_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceSpec:
    """A limited-use resource the class creates at level 1, full.

    `maximum` is `("column", header)` - read from `ClassLevel.columns`; `("fixed", n)`;
    `("ability_mod_min1", ability)`; or `("per_level", n)` (n x class level).
    `reset_on` uses `CharacterResource.RESET_CHOICES`: "other" is a partial recovery on a short
    rest and a full one on a long rest (Rage, Second Wind).
    Spending and recovering resources is deliberately not designed here (CLAUDE.md, "Open design
    question") - creation only creates them full.
    """

    name: str
    maximum: tuple
    reset_on: str


@dataclass(frozen=True)
class ToolPickSpec:
    """A tool proficiency chosen from a kind of tool. `kinds` are the source's placeholders
    (`anyMusicalInstrument`, `anyArtisansTool`); more than one means "one of these kinds" - the
    source lists Monk's two as separate grants but the text says to choose *one*."""

    kinds: tuple[str, ...]
    count: int


@dataclass(frozen=True)
class ClassSpec:
    weapon_mastery: WeaponMasterySpec | None = None
    #: Fighter: a feat of category "Fighting Style".
    fighting_style: bool = False
    #: The `Feature.name` holding the order choice ("Divine Order"), and its options.
    order_feature: str = ""
    orders: tuple[OrderOption, ...] = ()
    #: Rogue: Expertise in this many of the character's proficient skills.
    expertise: int = 0
    #: Wizard: level 1 spells in the spellbook (the prepared ones are chosen from these).
    spellbook: int = 0
    #: Warlock: Eldritch Invocations known at level 1.
    invocations: int = 0
    languages: tuple[str, ...] = ()  # granted outright
    extra_languages: int = 0  # granted as a free choice from the language tables
    always_prepared: tuple[str, ...] = ()  # spell ids that never count against the limit
    tool_pick: ToolPickSpec | None = None
    resources: tuple[ResourceSpec, ...] = ()
    #: `(ability, shield_allowed)` for a non-armor AC formula (10 + Dex + ability).
    unarmored_defense: tuple[str, bool] | None = None
    #: Skills the skill-choice list is restricted to are in `ChoiceDefinition`, not here.
    notes: str = field(default="", compare=False)


_LONG = "long_rest"

CLASS_SPEC: dict[str, ClassSpec] = {
    "barbarian": ClassSpec(
        weapon_mastery=WeaponMasterySpec(2, melee_only=True),
        resources=(ResourceSpec("Rage", ("column", "Rages"), "other"),),
        unarmored_defense=("con", True),
    ),
    "bard": ClassSpec(
        tool_pick=ToolPickSpec(("anyMusicalInstrument",), 3),
        resources=(ResourceSpec("Bardic Inspiration", ("ability_mod_min1", "cha"), _LONG),),
    ),
    "cleric": ClassSpec(
        order_feature="Divine Order",
        orders=(
            OrderOption("Protector", weapon_categories=("martial",), armor_categories=("heavy",)),
            OrderOption(
                "Thaumaturge",
                extra_cantrips=1,
                wisdom_bonus_skills=("arcana", "religion"),
            ),
        ),
    ),
    "druid": ClassSpec(
        order_feature="Primal Order",
        orders=(
            OrderOption("Warden", weapon_categories=("martial",), armor_categories=("medium",)),
            OrderOption(
                "Magician",
                extra_cantrips=1,
                wisdom_bonus_skills=("arcana", "nature"),
            ),
        ),
        languages=("druidic",),
        always_prepared=("speak-with-animals",),
    ),
    "fighter": ClassSpec(
        weapon_mastery=WeaponMasterySpec(3),
        fighting_style=True,
        resources=(ResourceSpec("Second Wind", ("column", "Second Wind"), "other"),),
    ),
    "monk": ClassSpec(
        tool_pick=ToolPickSpec(("anyArtisansTool", "anyMusicalInstrument"), 1),
        unarmored_defense=("wis", False),
    ),
    "paladin": ClassSpec(
        weapon_mastery=WeaponMasterySpec(2, proficient_only=True),
        resources=(ResourceSpec("Lay on Hands", ("per_level", 5), _LONG),),
    ),
    "ranger": ClassSpec(
        weapon_mastery=WeaponMasterySpec(2, proficient_only=True),
        always_prepared=("hunters-mark",),
        resources=(ResourceSpec("Favored Enemy", ("column", "Favored Enemy"), _LONG),),
    ),
    "rogue": ClassSpec(
        weapon_mastery=WeaponMasterySpec(2, proficient_only=True),
        expertise=2,
        languages=("thieves-cant",),
        extra_languages=1,
    ),
    "sorcerer": ClassSpec(
        resources=(ResourceSpec("Innate Sorcery", ("fixed", 2), _LONG),),
    ),
    "warlock": ClassSpec(invocations=1),
    "wizard": ClassSpec(
        spellbook=6,
        resources=(ResourceSpec("Arcane Recovery", ("fixed", 1), _LONG),),
    ),
}


def spec_for(class_id: str) -> ClassSpec:
    return CLASS_SPEC[class_id]
