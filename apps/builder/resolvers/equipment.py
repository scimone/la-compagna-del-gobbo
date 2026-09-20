"""Starting equipment: the class's and the background's "A or B" packages -> inventory + gold.

Each source offers lettered options (Fighter A/B/C, every background A/B). An option is a list of
rows; a row is one item, a "pick any X" group (Holy Symbol), or a lump of gold (in copper). A pack
is expanded into its individual items, and each of those stays traceable to the pack (D3 in
`docs/character_creation_plan.md`) via `ItemGrant.parent`.
"""

from dataclasses import dataclass

from apps.rules.models import Equipment

SOURCES = ("class", "background")


@dataclass
class ItemGrant:
    equipment: Equipment
    quantity: int = 1
    #: Index (in the same list) of the pack this item came out of, or `None`.
    parent: int | None = None
    source: str = ""


def source_object(draft, source: str):
    return draft.klass if source == "class" else draft.background


def option_rows(obj) -> dict[str, list]:
    """`{"A": [row, ...], "B": [...]}` for a class or background, in the source's order."""
    rows: dict[str, list] = {}
    if obj is None:
        return rows
    for row in obj.starting_equipment_options.select_related("item", "group").order_by(
        "option", "id"
    ):
        rows.setdefault(row.option, []).append(row)
    return rows


def group_key(source: str, group_id: str) -> str:
    return f"{source}:{group_id}"


def resolve(draft) -> tuple[list[ItemGrant], int, list[tuple[str, str]]]:
    """`(items, gold in copper, problems)`; a problem is `(code, path)`: `missing_option` or
    `missing_group_pick`. Partial drafts resolve to whatever is decided so far."""
    items: list[ItemGrant] = []
    gold = 0
    problems: list[tuple[str, str]] = []
    groups = draft.get("equipment.groups", {})
    for source in SOURCES:
        obj = source_object(draft, source)
        if obj is None:
            continue
        letter = draft.get(f"equipment.{source}")
        rows = option_rows(obj).get(letter or "")
        if not rows:
            problems.append(("missing_option", f"equipment.{source}"))
            continue
        for row in rows:
            if row.gold_value is not None:
                gold += row.gold_value
                continue
            item = row.item
            if row.group_id:
                picked = groups.get(group_key(source, row.group_id))
                item = row.group.items.filter(id=picked).first() if picked else None
                if item is None:
                    problems.append(
                        ("missing_group_pick", f"equipment.groups.{source}:{row.group_id}")
                    )
                    continue
            _add(items, item, row.quantity, source)
    return items, gold, problems


def _add(items: list[ItemGrant], item: Equipment, quantity: int, source: str) -> None:
    contents = list(item.pack_content_rows.select_related("item").order_by("item__name"))
    items.append(ItemGrant(item, quantity, source=source))
    if contents:
        pack_index = len(items) - 1
        for content in contents:
            items.append(
                ItemGrant(content.item, content.quantity, parent=pack_index, source=source)
            )


def split_coins(copper: int) -> dict[str, int]:
    """Copper -> gp/sp/cp. (Electrum and platinum are never produced by starting gold.)"""
    gold, rest = divmod(copper, 100)
    silver, copper = divmod(rest, 10)
    return {"gold": gold, "silver": silver, "copper": copper}
