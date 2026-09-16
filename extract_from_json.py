import json
import sys
from pathlib import Path
from typing import Any


def _get_items(data: Any) -> list[dict]:
    if isinstance(data, dict) and "items" in data:
        return data["items"]

    if isinstance(data, list):
        return data

    raise TypeError("Expected a JSON list or an object with an 'items' array")


def extract_from_json(relative_path: str, source: str = "XPHB") -> None:
    """
    Filters top-level JSON entries by their 'source' value.
    Modifies the file in place.
    """
    path = Path(relative_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = _get_items(data)

    filtered = [item for item in items if item.get("source") == source]

    if isinstance(data, dict) and "items" in data:
        data["items"] = filtered

        if isinstance(data.get("meta"), dict):
            data["meta"]["count"] = len(filtered)
    else:
        data = filtered

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def extract_from_json_by_id(relative_path: str, item_id: str) -> None:
    """
    Filters top-level JSON entries by their 'id' value.
    Modifies the file in place.
    """
    path = Path(relative_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = _get_items(data)

    filtered = [item for item in items if item.get("id") == item_id]

    if isinstance(data, dict) and "items" in data:
        data["items"] = filtered

        if isinstance(data.get("meta"), dict):
            data["meta"]["count"] = len(filtered)
    else:
        data = filtered

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def extract_from_json_by_data_name(relative_path: str, data_name: str) -> None:
    """
    Filters the top-level 'data' array by the entry's 'name'.

    Example:

        {
            "data": [
                {
                    "type": "section",
                    "name": "Playing the Game",
                    ...
                }
            ]
        }

    Only the matching entry is kept.
    """
    path = Path(relative_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise TypeError("Expected a JSON object with a 'data' array")

    filtered = [
        item for item in data["data"] if isinstance(item, dict) and item.get("name") == data_name
    ]

    data["data"] = filtered

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"Found {len(filtered)} matching entries.")

    for item in filtered:
        print(item.get("name"))


def _type_name(value) -> str:
    if value is None:
        return "null"

    if isinstance(value, bool):
        return "bool"

    if isinstance(value, int):
        return "int"

    if isinstance(value, float):
        return "float"

    if isinstance(value, str):
        return "str"

    if isinstance(value, list):
        return "list"

    if isinstance(value, dict):
        return "dict"

    return type(value).__name__


def _infer_value_schema(values: list) -> dict[str, Any]:
    types = set()
    dict_values = []
    list_values = []

    for value in values:
        t = _type_name(value)
        types.add(t)

        if t == "dict":
            dict_values.append(value)

        elif t == "list":
            list_values.extend(value)

    schema: dict[str, Any] = {"type": sorted(types)}

    if dict_values:
        schema["properties"] = _infer_object_schema(dict_values)

    if list_values:
        schema["items"] = _infer_value_schema(list_values)

    return schema


def _infer_object_schema(objects: list[dict]) -> dict[str, Any]:
    keys = set()

    for obj in objects:
        keys.update(obj.keys())

    total = len(objects)
    schema: dict[str, Any] = {}

    for key in sorted(keys):
        values = [obj[key] for obj in objects if key in obj]

        field_schema = _infer_value_schema(values)

        field_schema["required"] = len(values) == total

        schema[key] = field_schema

    return schema


def _compact_field_lines(name: str, field_schema: dict[str, Any], indent: int) -> list[str]:
    type_str = "|".join(field_schema["type"])

    optional = "" if field_schema.get("required", True) else "?"

    lines = [f"{'  ' * indent}{name}{optional}: {type_str}"]

    if "properties" in field_schema:
        for key, sub_schema in field_schema["properties"].items():
            lines.extend(_compact_field_lines(key, sub_schema, indent + 1))

    if "items" in field_schema:
        lines.extend(_compact_field_lines("[]", field_schema["items"], indent + 1))

    return lines


def _print_compact_schema(schema: dict[str, Any]) -> None:
    for name, field_schema in schema.items():
        print("\n".join(_compact_field_lines(name, field_schema, 0)))


def infer_schema(relative_path: str) -> dict[str, Any]:
    path = Path(relative_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    schema = _infer_object_schema(_get_items(data))

    schema_path = path.with_name(f"{path.stem}_schema{path.suffix}")

    with schema_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    _print_compact_schema(schema)

    return schema


def list_item_names(relative_path: str) -> None:
    path = Path(relative_path)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for item in _get_items(data):
        print(item.get("name"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python extract_from_json.py extract <relative_path> [source]")
        print("  python extract_from_json.py id <relative_path> <id>")
        print("  python extract_from_json.py data-name <relative_path> <name>")
        print("  python extract_from_json.py schema <relative_path>")
        print("  python extract_from_json.py names <relative_path>")
        sys.exit(1)

    command = sys.argv[1]

    # ----------------------------------------
    # Filter by source
    # ----------------------------------------

    if command == "extract":
        if len(sys.argv) < 3:
            print("Usage: python extract_from_json.py extract <relative_path> [source]")
            sys.exit(1)

        relative_path = sys.argv[2]

        source = sys.argv[3] if len(sys.argv) > 3 else "XPHB"

        extract_from_json(relative_path, source)

        list_item_names(relative_path)

    # ----------------------------------------
    # Filter by id
    # ----------------------------------------

    elif command == "id":
        if len(sys.argv) < 4:
            print("Usage: python extract_from_json.py id <relative_path> <id>")
            sys.exit(1)

        relative_path = sys.argv[2]
        item_id = sys.argv[3]

        extract_from_json_by_id(relative_path, item_id)

        list_item_names(relative_path)

    # ----------------------------------------
    # Filter by data.name
    # ----------------------------------------

    elif command == "data-name":
        if len(sys.argv) < 4:
            print("Usage: python extract_from_json.py data-name <relative_path> <name>")
            sys.exit(1)

        relative_path = sys.argv[2]
        data_name = sys.argv[3]

        extract_from_json_by_data_name(relative_path, data_name)

    # ----------------------------------------
    # Generate schema
    # ----------------------------------------

    elif command == "schema":
        if len(sys.argv) < 3:
            print("Usage: python extract_from_json.py schema <relative_path>")
            sys.exit(1)

        relative_path = sys.argv[2]

        infer_schema(relative_path)

    # ----------------------------------------
    # List names
    # ----------------------------------------

    elif command == "names":
        if len(sys.argv) < 3:
            print("Usage: python extract_from_json.py names <relative_path>")
            sys.exit(1)

        relative_path = sys.argv[2]

        list_item_names(relative_path)

    # ----------------------------------------
    # Unknown command
    # ----------------------------------------

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
