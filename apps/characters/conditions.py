"""What each condition of the rules glossary does to a character.

The rules *text* is data (`rules.Condition`, imported from db/conditions.json, translated like the
other catalogs); this module holds what the text means for the sheet's numbers - the `Condition`
rows below carry only mechanics, keyed by the same ids, and `tests/test_conditions.py` fails if
the two stop agreeing. A character stores the conditions it has (`Character.conditions`, a list
of ids; conditions don't stack) and its Exhaustion level (`Character.exhaustion`, 0-6, the one
that does).

`active()` resolves what is in effect: the stored ones plus the ones they apply (Paralyzed makes
you Incapacitated, Unconscious makes you Prone and Incapacitated, ...). Dropping to 0 hit points
stores Unconscious, regaining any hit points removes it (`play.sync_unconscious()`) - the
Handbook's "Falling Unconscious". `effects()` boils the active ones down to what `derived_stats`
applies - Speed and the Exhaustion penalty on D20 Tests - and the sheet shows.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

EXHAUSTION_MAX = 6
EXHAUSTION_ID = "exhaustion"


@dataclass(frozen=True)
class Condition:
    id: str
    #: Conditions this one applies while it lasts (Paralyzed is also Incapacitated).
    implies: tuple[str, ...] = ()
    #: Conditions that stay when this one ends: "When this condition ends, you remain Prone."
    remains: tuple[str, ...] = ()
    speed_zero: bool = False
    #: Your own attack rolls: "advantage" / "disadvantage".
    own_attacks: str = ""
    #: Attack rolls against you: "advantage" / "disadvantage" / "prone" (Advantage from within
    #: 5 feet, Disadvantage from farther away).
    attacks_against: str = ""
    ability_checks_disadvantage: bool = False
    #: Your Initiative rolls: "advantage" / "disadvantage".
    initiative: str = ""
    #: Saving throws you automatically fail ("str", "dex").
    auto_fail_saves: tuple[str, ...] = ()
    dex_saves_disadvantage: bool = False
    #: A hit from within 5 feet is a Critical Hit.
    crit_within_5: bool = False
    incapacitated: bool = False


CONDITIONS: tuple[Condition, ...] = (
    Condition("blinded", own_attacks="disadvantage", attacks_against="advantage"),
    Condition("charmed"),
    Condition("deafened"),
    Condition("frightened", own_attacks="disadvantage", ability_checks_disadvantage=True),
    Condition("grappled", speed_zero=True),
    Condition("incapacitated", incapacitated=True, initiative="disadvantage"),
    Condition(
        "invisible", own_attacks="advantage", attacks_against="disadvantage", initiative="advantage"
    ),
    Condition(
        "paralyzed",
        implies=("incapacitated",),
        speed_zero=True,
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
        crit_within_5=True,
    ),
    Condition(
        "petrified",
        implies=("incapacitated",),
        speed_zero=True,
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
    ),
    Condition("poisoned", own_attacks="disadvantage", ability_checks_disadvantage=True),
    Condition("prone", own_attacks="disadvantage", attacks_against="prone"),
    Condition(
        "restrained",
        speed_zero=True,
        own_attacks="disadvantage",
        attacks_against="advantage",
        dex_saves_disadvantage=True,
    ),
    Condition(
        "stunned",
        implies=("incapacitated",),
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
    ),
    Condition(
        "unconscious",
        implies=("prone", "incapacitated"),
        remains=("prone",),
        speed_zero=True,
        attacks_against="advantage",
        auto_fail_saves=("str", "dex"),
        crit_within_5=True,
    ),
)
BY_ID = {c.id: c for c in CONDITIONS}
UNCONSCIOUS = "unconscious"


def active(character) -> set[str]:
    """Every condition in effect: the stored ones and those they apply."""
    ids = {c for c in character.conditions if c in BY_ID}
    pending = list(ids)
    while pending:
        for implied in BY_ID[pending.pop()].implies:
            if implied not in ids:
                ids.add(implied)
                pending.append(implied)
    return ids


def bloodied(character) -> bool:
    """Whether the character is Bloodied: half its hit points or fewer remain (and it is up)."""
    maximum = character.hit_point_maximum
    return 0 < character.current_hit_points <= maximum // 2 if maximum else False


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
    initiative: set[str]
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
        initiative={c.initiative for c in found if c.initiative},
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
    if fx.initiative == {"advantage", "disadvantage"}:
        lines.append(_("Initiative: Advantage and Disadvantage cancel out"))
    elif fx.initiative == {"disadvantage"}:
        lines.append(_("Disadvantage on Initiative"))
    elif fx.initiative == {"advantage"}:
        lines.append(_("Advantage on Initiative"))
    if fx.auto_fail_saves:
        lines.append(_("You automatically fail Strength and Dexterity saving throws"))
    elif fx.dex_saves_disadvantage:
        lines.append(_("Disadvantage on Dexterity saving throws"))
    if fx.crit_within_5:
        lines.append(_("Hits from within 5 feet are Critical Hits"))
    return lines
