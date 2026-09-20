"""Proficiencies: what a class/background grants, and the "does this weapon count" test.

Grants in `db/` use small placeholder idioms: `{"light": True}` for an armor category,
`{"anyMusicalInstrument": 3}` for "pick three instruments", `{"all": {"fromFilter": ...}}` for a
filtered weapon grant (Monk, Rogue). This module turns them into plain sets and a predicate.
"""

from dataclasses import dataclass, field

from apps.rules.models import Background, Class, Equipment

#: The source's tool placeholders -> the `EquipmentType.id` that enumerates the choices.
TOOL_KIND_TYPE = {"anyMusicalInstrument": "ins", "anyArtisansTool": "at", "anyGamingSet": "gs"}
#: `fromFilter` property names -> `EquipmentProperty.id`.
_PROPERTY_IDS = {"light": "l", "finesse": "f"}


@dataclass
class WeaponProficiency:
    """Weapon proficiency as categories ("simple", "martial") plus filtered grants: a weapon of
    `category` that has *any* of `properties` (Rogue: martial + finesse-or-light), plus loose named
    grants such as "improvised" (Tavern Brawler)."""

    categories: set[str] = field(default_factory=set)
    filtered: list[tuple[str, set[str]]] = field(default_factory=list)
    named: set[str] = field(default_factory=set)

    def covers(self, weapon: Equipment) -> bool:
        if weapon.weapon_category in self.categories:
            return True
        property_ids = {p.id for p in weapon.properties.all()}
        return any(
            weapon.weapon_category == category and property_ids & properties
            for category, properties in self.filtered
        )

    def add_grant(self, grant: dict) -> None:
        for key, value in grant.items():
            if key in ("simple", "martial") and value is True:
                self.categories.add(key)
            elif key == "all" and isinstance(value, dict):
                # "type=martial weapon|property=light;finesse"
                parts = dict(p.split("=", 1) for p in value["fromFilter"].split("|"))
                names = parts.get("property", "").split(";")
                self.filtered.append(
                    (
                        parts["type"].removesuffix(" weapon"),
                        {_PROPERTY_IDS[n] for n in names if n in _PROPERTY_IDS},
                    )
                )
            elif value is True:
                self.named.add(key)


def class_weapon_proficiency(klass: Class) -> WeaponProficiency:
    prof = WeaponProficiency()
    for grant in klass.weapon_proficiencies:
        prof.add_grant(grant)
    return prof


def class_armor_categories(klass: Class) -> set[str]:
    """`{"light", "medium", "heavy", "shield"}` the class is trained in."""
    return {k for grant in klass.armor_proficiencies for k, v in grant.items() if v is True}


def named_tool_ids(grants: list[dict]) -> list[str]:
    """Equipment ids for the named (non-placeholder) tools in a `tool_proficiencies`/`tools` list
    (`{"thieves' tools": True}`) - matched on the lowercased `Equipment.name`."""
    names = [k for grant in grants for k, v in grant.items() if v is True]
    by_name = {
        e.name_en.lower(): e.id
        for e in Equipment.objects.filter(type__id__in=["t", "at", "gs", "ins"])
    }
    return [by_name[n] for n in names if n in by_name]


def tool_pick(grants: list[dict]) -> tuple[list[str], int] | None:
    """The `(kinds, count)` of the placeholder grant in `grants`, e.g. `(["anyGamingSet"], 1)`."""
    kinds = [k for grant in grants for k in grant if k in TOOL_KIND_TYPE]
    counts = [v for grant in grants for k, v in grant.items() if k in TOOL_KIND_TYPE]
    return (kinds, counts[0]) if kinds else None


def tool_options(kinds: list[str]):
    """Every tool of the given placeholder kinds, as an `Equipment` queryset."""
    return Equipment.objects.filter(type_id__in=[TOOL_KIND_TYPE[k] for k in kinds]).order_by("name")


def background_tool_grant(background: Background) -> tuple[list[str], tuple[list[str], int] | None]:
    """`(fixed tool ids, pick)` for a background."""
    return named_tool_ids(background.tools), tool_pick(background.tools)
