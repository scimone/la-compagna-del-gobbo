"""The conditions of the rules glossary (SRD 5.2) and what each one does to a character.

They are static rules text that is not in `db/` (the Handbook's Conditions section only names them
and points at the glossary), so - like `builder/tables.py` - they are code. A character stores
the ones it has (`Character.conditions`, a list of ids; conditions don't stack) and its
Exhaustion level (`Character.exhaustion`, 0-6, the one condition that does stack).

`active()` resolves what is really in effect: the stored ones, the ones they apply (Paralyzed
makes you Incapacitated, Unconscious makes you Prone and Incapacitated, ...) and Unconscious at
0 hit points. `effects()` boils that down to the numbers and rules the sheet shows and
`derived_stats` applies: Speed, the d20 Test penalty of Exhaustion, and Advantage/Disadvantage.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

EXHAUSTION_MAX = 6


@dataclass(frozen=True)
class Condition:
    id: str
    name: object
    rules: tuple
    #: Conditions this one applies (Paralyzed is also Incapacitated).
    implies: tuple[str, ...] = ()
    speed_zero: bool = False
    #: Your own attack rolls: "advantage" / "disadvantage".
    own_attacks: str = ""
    #: Attack rolls against you: "advantage" / "disadvantage" / "prone" (Advantage from within
    #: 5 feet, Disadvantage from farther away).
    attacks_against: str = ""
    ability_checks_disadvantage: bool = False
    #: Saving throws you automatically fail ("str", "dex").
    auto_fail_saves: tuple[str, ...] = ()
    dex_saves_disadvantage: bool = False
    #: A hit from within 5 feet is a Critical Hit.
    crit_within_5: bool = False
    incapacitated: bool = False


CONDITIONS: tuple[Condition, ...] = (
    Condition(
        "blinded",
        _("Blinded"),
        (
            _("You can't see and automatically fail any ability check that requires sight."),
            _("Attack rolls against you have Advantage, and your attack rolls have Disadvantage."),
        ),
        own_attacks="disadvantage",
        attacks_against="advantage",
    ),
    Condition(
        "charmed",
        _("Charmed"),
        (
            _(
                "You can't attack the charmer or target the charmer with damaging abilities or "
                "magical effects."
            ),
            _("The charmer has Advantage on any ability check to interact with you socially."),
        ),
    ),
    Condition(
        "deafened",
        _("Deafened"),
        (_("You can't hear and automatically fail any ability check that requires hearing."),),
    ),
    Condition(
        "frightened",
        _("Frightened"),
        (
            _(
                "You have Disadvantage on ability checks and attack rolls while the source of "
                "your fear is within line of sight."
            ),
            _("You can't willingly move closer to the source of your fear."),
        ),
        own_attacks="disadvantage",
        ability_checks_disadvantage=True,
    ),
    Condition(
        "grappled",
        _("Grappled"),
        (
            _("Your Speed is 0 and can't increase."),
            _("You have Disadvantage on attack rolls against any target other than the grappler."),
            _(
                "The grappler can drag or carry you when it moves, but every foot of movement "
                "costs it 1 extra foot unless you are Tiny or two or more sizes smaller than it."
            ),
        ),
        speed_zero=True,
    ),
    Condition(
        "incapacitated",
        _("Incapacitated"),
        (
            _("You can't take any actions, Bonus Actions, or Reactions."),
            _("Your Concentration is broken."),
            _("You can't speak."),
            _(
                "If you are Incapacitated when you roll Initiative, you have Disadvantage on the "
                "roll."
            ),
        ),
        incapacitated=True,
    ),
    Condition(
        "invisible",
        _("Invisible"),
        (
            _(
                "You aren't affected by any effect that requires its target to be seen unless the "
                "effect's creator can somehow see you. Any equipment you are wearing or carrying "
                "is also concealed."
            ),
            _(
                "Attack rolls against you have Disadvantage, and your attack rolls have "
                "Advantage. If a creature can somehow see you, you don't gain this benefit "
                "against that creature."
            ),
        ),
        own_attacks="advantage",
        attacks_against="disadvantage",
    ),
    Condition(
        "paralyzed",
        _("Paralyzed"),
        (
            _("You have the Incapacitated condition."),
            _("Your Speed is 0 and can't increase."),
            _("You automatically fail Strength and Dexterity saving throws."),
            _("Attack rolls against you have Advantage."),
            _(
                "Any attack roll that hits you is a Critical Hit if the attacker is within 5 feet "
                "of you."
            ),
        ),
        implies=("incapacitated",),
        speed_zero=True,
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
        crit_within_5=True,
    ),
    Condition(
        "petrified",
        _("Petrified"),
        (
            _(
                "You are transformed, along with any nonmagical object you are wearing or "
                "carrying, into a solid inanimate substance (usually stone). Your weight "
                "increases by a factor of ten, and you cease aging."
            ),
            _("You have the Incapacitated condition."),
            _("Your Speed is 0 and can't increase."),
            _("Attack rolls against you have Advantage."),
            _("You automatically fail Strength and Dexterity saving throws."),
            _("You have Resistance to all damage."),
            _("You are immune to the Poisoned condition."),
        ),
        implies=("incapacitated",),
        speed_zero=True,
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
    ),
    Condition(
        "poisoned",
        _("Poisoned"),
        (_("You have Disadvantage on attack rolls and ability checks."),),
        own_attacks="disadvantage",
        ability_checks_disadvantage=True,
    ),
    Condition(
        "prone",
        _("Prone"),
        (
            _(
                "Your only movement options are to crawl or to spend an amount of movement equal "
                "to half your Speed (round down) to right yourself and thereby end the condition. "
                "If your Speed is 0, you can't right yourself."
            ),
            _("You have Disadvantage on attack rolls."),
            _(
                "An attack roll against you has Advantage if the attacker is within 5 feet of "
                "you. Otherwise, that attack roll has Disadvantage."
            ),
        ),
        own_attacks="disadvantage",
        attacks_against="prone",
    ),
    Condition(
        "restrained",
        _("Restrained"),
        (
            _("Your Speed is 0 and can't increase."),
            _("Attack rolls against you have Advantage, and your attack rolls have Disadvantage."),
            _("You have Disadvantage on Dexterity saving throws."),
        ),
        speed_zero=True,
        own_attacks="disadvantage",
        attacks_against="advantage",
        dex_saves_disadvantage=True,
    ),
    Condition(
        "stunned",
        _("Stunned"),
        (
            _("You have the Incapacitated condition."),
            _("You automatically fail Strength and Dexterity saving throws."),
            _("Attack rolls against you have Advantage."),
        ),
        implies=("incapacitated",),
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
    ),
    Condition(
        "unconscious",
        _("Unconscious"),
        (
            _(
                "You have the Prone and Incapacitated conditions, and you drop whatever you're "
                "holding. When this condition ends, you remain Prone."
            ),
            _("Your Speed is 0 and can't increase."),
            _("Attack rolls against you have Advantage."),
            _("You automatically fail Strength and Dexterity saving throws."),
            _(
                "Any attack roll that hits you is a Critical Hit if the attacker is within 5 feet "
                "of you."
            ),
            _("You are unaware of your surroundings."),
        ),
        implies=("prone", "incapacitated"),
        speed_zero=True,
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
        crit_within_5=True,
    ),
)
BY_ID = {c.id: c for c in CONDITIONS}

EXHAUSTION_NAME = _("Exhaustion")
EXHAUSTION_RULES = (
    _("Exhaustion is cumulative: each time you receive it, you gain 1 level, up to 6."),
    _("When you make a D20 Test, the roll is reduced by 2 times your Exhaustion level."),
    _("Your Speed is reduced by 5 feet times your Exhaustion level."),
    _("You die if your Exhaustion level reaches 6."),
    _("Finishing a Long Rest removes 1 of your Exhaustion levels."),
)


def active(character) -> set[str]:
    """Every condition in effect: the stored ones, those they apply, and Unconscious at 0 HP."""
    ids = {c for c in character.conditions if c in BY_ID}
    if character.current_hit_points < 1:
        ids.add("unconscious")
    pending = list(ids)
    while pending:
        for implied in BY_ID[pending.pop()].implies:
            if implied not in ids:
                ids.add(implied)
                pending.append(implied)
    return ids


@dataclass
class Effects:
    conditions: list[Condition]
    exhaustion: int
    speed_zero: bool
    d20_penalty: int
    speed_penalty: int
    incapacitated: bool
    own_attacks: set[str]
    attacks_against: set[str]
    ability_checks_disadvantage: bool
    auto_fail_saves: set[str]
    dex_saves_disadvantage: bool
    crit_within_5: bool


def effects(character) -> Effects:
    """What the character's conditions amount to right now."""
    found = [BY_ID[i] for i in sorted(active(character))]
    exhaustion = max(0, min(EXHAUSTION_MAX, character.exhaustion))
    return Effects(
        conditions=found,
        exhaustion=exhaustion,
        speed_zero=any(c.speed_zero for c in found),
        d20_penalty=2 * exhaustion,
        speed_penalty=5 * exhaustion,
        incapacitated=any(c.incapacitated for c in found),
        own_attacks={c.own_attacks for c in found if c.own_attacks},
        attacks_against={c.attacks_against for c in found if c.attacks_against},
        ability_checks_disadvantage=any(c.ability_checks_disadvantage for c in found),
        auto_fail_saves={s for c in found for s in c.auto_fail_saves},
        dex_saves_disadvantage=any(c.dex_saves_disadvantage for c in found),
        crit_within_5=any(c.crit_within_5 for c in found),
    )


def summary(character) -> list:
    """The in-effect lines for the sheet's Conditions card, most important first. Advantage and
    Disadvantage on the same roll cancel out, so a roll with both says so."""
    fx = effects(character)
    lines = []
    if fx.exhaustion:
        lines.append(
            _("Exhaustion %(level)s: D20 Tests -%(penalty)s, Speed -%(speed)s ft")
            % {"level": fx.exhaustion, "penalty": fx.d20_penalty, "speed": fx.speed_penalty}
        )
    if fx.incapacitated:
        lines.append(_("You can't take actions, Bonus Actions or Reactions"))
    if fx.speed_zero:
        lines.append(_("Speed 0"))
    own_adv = "advantage" in fx.own_attacks
    own_dis = "disadvantage" in fx.own_attacks
    if own_adv and own_dis:
        lines.append(_("Your attack rolls: Advantage and Disadvantage cancel out"))
    elif own_dis:
        lines.append(_("Disadvantage on your attack rolls"))
    elif own_adv:
        lines.append(_("Advantage on your attack rolls"))
    against = fx.attacks_against
    adv = "advantage" in against
    dis = "disadvantage" in against
    if "prone" in against:
        if adv or dis:
            lines.append(_("Attack rolls against you: Advantage and Disadvantage may cancel out"))
        else:
            lines.append(_("Attack rolls against you: Advantage within 5 ft, Disadvantage farther"))
    elif adv and dis:
        lines.append(_("Attack rolls against you: Advantage and Disadvantage cancel out"))
    elif adv:
        lines.append(_("Attack rolls against you have Advantage"))
    elif dis:
        lines.append(_("Attack rolls against you have Disadvantage"))
    if fx.ability_checks_disadvantage:
        lines.append(_("Disadvantage on ability checks"))
    if fx.auto_fail_saves:
        lines.append(_("You automatically fail Strength and Dexterity saving throws"))
    elif fx.dex_saves_disadvantage:
        lines.append(_("Disadvantage on Dexterity saving throws"))
    if fx.crit_within_5:
        lines.append(_("Hits from within 5 feet are Critical Hits"))
    return lines
