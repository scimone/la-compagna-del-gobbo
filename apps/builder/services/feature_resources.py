"""Limited-use features that aren't class-table resources: species traits, feats and subclass
features that say "N times, regaining all uses on a Long Rest" (Breath Weapon, Luck Points,
Warding Flare, ...).

`FEATURE_RESOURCES` names each one once: which feature carries it (a species, a feat, a
subclass or - for a class feature `LEVEL_RESOURCES` doesn't list - a class), how many uses and
when they come back. `refresh()` then gives a character a `CharacterResource` for every such
feature it has, and keeps the maximum current as levels and ability scores change; nothing is
ever removed. The class-table resources (Rage, Channel Divinity, ...) stay in
`progression_spec.LEVEL_RESOURCES`. `tests/test_feature_resources.py` fails if a row names a
feature the imported data doesn't have.

Maximums: `("fixed", n)`, `("proficiency",)`, `("mod", ability)` (at least 1),
`("by_class_level", class, {level: n})` (the highest level reached) and
`("plus_class_level", class, n)`. Reset: `CharacterResource.reset_on` ("short_rest" is the
"Short Rest or Long Rest" wording; "other" is one back on a short rest, all on a long one).
"""

from dataclasses import dataclass

from apps.characters.models import Character, CharacterResource

from .. import tables

_LONG, _SHORT, _OTHER = "long_rest", "short_rest", "other"
_ONE = ("fixed", 1)
_PB = ("proficiency",)
_PSIONIC_DICE = {3: 4, 5: 6, 9: 8, 13: 10, 17: 12}


@dataclass(frozen=True)
class FeatureResource:
    owner: str  # "species" | "feat" | "subclass" | "class"
    key: str  # species/feat/class id, or the subclass's English name
    feature: str  # `Feature.name_en` (a "(...)" suffix, as on a lineage, is ignored)
    maximum: tuple
    reset: str = _LONG
    #: Character level the trait starts at, where it is not level 1 ("When you reach character
    #: level 5"): species traits are all granted at creation, so their resource waits for this.
    min_level: int = 1


FEATURE_RESOURCES: tuple[FeatureResource, ...] = (
    # species
    FeatureResource("species", "orc", "Adrenaline Rush", _PB, _SHORT),
    FeatureResource("species", "orc", "Relentless Endurance", _ONE),
    FeatureResource("species", "dragonborn", "Breath Weapon", _PB),
    FeatureResource("species", "dragonborn", "Draconic Flight", _ONE, min_level=5),
    FeatureResource("species", "aasimar", "Healing Hands", _ONE),
    FeatureResource("species", "aasimar", "Celestial Revelation", _ONE, min_level=3),
    FeatureResource("species", "goliath", "Giant Ancestry", _PB),
    FeatureResource("species", "goliath", "Large Form", _ONE, min_level=5),
    FeatureResource("species", "dwarf", "Stonecunning", _PB),
    # feats
    FeatureResource("feat", "lucky", "Luck Points", _PB),
    FeatureResource("feat", "mage-slayer", "Guarded Mind", _ONE, _SHORT),
    FeatureResource("feat", "ritual-caster", "Quick Ritual", _ONE),
    # class features outside the class tables
    FeatureResource("class", "barbarian", "Persistent Rage", _ONE),
    FeatureResource("class", "druid", "Wild Resurgence", _ONE),
    FeatureResource("class", "druid", "Archdruid", _ONE),
    FeatureResource("class", "sorcerer", "Sorcerous Restoration", _ONE),
    FeatureResource("class", "warlock", "Contact Patron", _ONE),
    # subclasses
    FeatureResource("subclass", "Light Domain", "Warding Flare", ("mod", "wis")),
    FeatureResource("subclass", "Light Domain", "Corona of Light", ("mod", "wis")),
    FeatureResource("subclass", "War Domain", "War Priest", ("mod", "wis"), _SHORT),
    FeatureResource("subclass", "Path of the Berserker", "Intimidating Presence", _ONE),
    FeatureResource("subclass", "Path of the Zealot", "Rage of the Gods", _ONE),
    FeatureResource("subclass", "Path of the Zealot", "Zealous Presence", _ONE),
    FeatureResource(
        "subclass",
        "Path of the Zealot",
        "Warrior of the Gods",
        ("by_class_level", "barbarian", {3: 4, 6: 5, 12: 6, 17: 7}),
    ),
    FeatureResource("subclass", "College of Glamour", "Beguiling Magic", _ONE),
    FeatureResource("subclass", "College of Glamour", "Mantle of Majesty", _ONE),
    FeatureResource("subclass", "College of Glamour", "Unbreakable Majesty", _ONE, _SHORT),
    FeatureResource("subclass", "Circle of the Moon", "Moonlight Step", ("mod", "wis")),
    FeatureResource("subclass", "Circle of the Stars", "Star Map", ("mod", "wis")),
    FeatureResource("subclass", "Battle Master", "Know Your Enemy", _ONE),
    FeatureResource(
        "subclass",
        "Psi Warrior",
        "Psionic Power",
        ("by_class_level", "fighter", _PSIONIC_DICE),
        _OTHER,
    ),
    FeatureResource(
        "subclass", "Soulknife", "Psionic Power", ("by_class_level", "rogue", _PSIONIC_DICE), _OTHER
    ),
    FeatureResource("subclass", "Soulknife", "Psychic Veil", _ONE),
    FeatureResource("subclass", "Soulknife", "Rend Mind", _ONE),
    FeatureResource("subclass", "Arcane Trickster", "Spell Thief", _ONE),
    FeatureResource("subclass", "Illusionist", "Illusory Self", _ONE, _SHORT),
    FeatureResource("subclass", "Diviner", "The Third Eye", _ONE, _SHORT),
    FeatureResource("subclass", "Warrior of the Open Hand", "Wholeness of Body", ("mod", "wis")),
    FeatureResource("subclass", "Warrior of Mercy", "Flurry of Healing and Harm", ("mod", "wis")),
    FeatureResource("subclass", "Warrior of Mercy", "Hand of Ultimate Mercy", _ONE),
    FeatureResource("subclass", "Oath of Devotion", "Holy Nimbus", _ONE),
    FeatureResource("subclass", "Oath of Glory", "Glorious Defense", ("mod", "cha")),
    FeatureResource("subclass", "Oath of Glory", "Living Legend", _ONE),
    FeatureResource("subclass", "Oath of the Ancients", "Elder Champion", _ONE),
    FeatureResource("subclass", "Oath of the Ancients", "Undying Sentinel", _ONE),
    FeatureResource("subclass", "Oath of Vengeance", "Avenging Angel", _ONE),
    FeatureResource("subclass", "Gloom Stalker", "Dread Ambusher", ("mod", "wis")),
    FeatureResource("subclass", "Fey Wanderer", "Misty Wanderer", ("mod", "wis")),
    FeatureResource("subclass", "Clockwork Sorcery", "Restore Balance", ("mod", "cha")),
    FeatureResource("subclass", "Clockwork Sorcery", "Trance of Order", _ONE),
    FeatureResource("subclass", "Clockwork Sorcery", "Clockwork Cavalcade", _ONE),
    FeatureResource("subclass", "Draconic Sorcery", "Dragon Wings", _ONE),
    FeatureResource("subclass", "Aberrant Sorcery", "Warping Implosion", _ONE),
    FeatureResource("subclass", "Wild Magic Sorcery", "Tamed Surge", _ONE),
    FeatureResource("subclass", "Archfey Patron", "Steps of the Fey", ("mod", "cha")),
    FeatureResource("subclass", "Archfey Patron", "Beguiling Defenses", _ONE),
    FeatureResource(
        "subclass", "Celestial Patron", "Healing Light", ("plus_class_level", "warlock", 1)
    ),
    FeatureResource("subclass", "Celestial Patron", "Searing Vengeance", _ONE),
    FeatureResource("subclass", "Fiend Patron", "Dark One's Own Luck", ("mod", "cha")),
    FeatureResource("subclass", "Fiend Patron", "Hurl Through Hell", _ONE),
    FeatureResource("subclass", "Great Old One Patron", "Clairvoyant Combatant", _ONE, _SHORT),
)


def _name_matches(feature_name: str, wanted: str) -> bool:
    return feature_name == wanted or feature_name.startswith(f"{wanted} (")


def _has(character: Character, row: FeatureResource, subclass_names: dict[str, str]) -> bool:
    if row.owner == "feat":
        return character.feats.filter(feat_id=row.key).exists()
    if row.owner == "species":
        if character.species_id != row.key:
            return False
        parent = {"feature__species_id": row.key}
    elif row.owner == "class":
        parent = {"feature__class_level__klass_id": row.key}
    else:
        if row.key not in subclass_names.values():
            return False
        parent = {"feature__subclass_level__subclass__name_en": row.key}
    return any(
        _name_matches(name, row.feature)
        for name in character.features.filter(**parent).values_list("feature__name_en", flat=True)
    )


def _maximum(character: Character, row: FeatureResource, levels: dict[str, int], total: int) -> int:
    kind, *args = row.maximum
    if kind == "fixed":
        return args[0]
    if kind == "proficiency":
        return tables.proficiency_bonus(total)
    if kind == "mod":
        score = getattr(character, tables.ABILITY_FIELDS[args[0]])
        return max(1, tables.ability_modifier(score))
    klass, extra = args[0], args[1]
    level = levels.get(klass, 0)
    if kind == "plus_class_level":
        return extra + level
    reached = [lv for lv in extra if lv <= level]
    return extra[max(reached)] if reached else 0


def refresh(character: Character) -> None:
    """Create or update the `CharacterResource` of every `FEATURE_RESOURCES` feature the
    character has. A raised maximum also raises the current uses by the difference."""
    classes = list(character.classes.select_related("subclass"))
    levels = {row.klass_id: row.level for row in classes}
    total = sum(levels.values()) or 1
    subclass_names = {row.klass_id: row.subclass.name_en for row in classes if row.subclass}
    existing = {r.name: r for r in CharacterResource.objects.filter(character=character)}
    for row in FEATURE_RESOURCES:
        if total < row.min_level or not _has(character, row, subclass_names):
            continue
        maximum = _maximum(character, row, levels, total)
        if maximum <= 0:
            continue
        current = existing.get(row.feature)
        if current is None:
            existing[row.feature] = CharacterResource.objects.create(
                character=character,
                name=row.feature,
                max_uses=maximum,
                current_uses=maximum,
                reset_on=row.reset,
            )
        elif current.max_uses != maximum:
            current.current_uses = min(
                maximum, current.current_uses + max(0, maximum - current.max_uses)
            )
            current.max_uses = maximum
            current.save(update_fields=["max_uses", "current_uses"])
