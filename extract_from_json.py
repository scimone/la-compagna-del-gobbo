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
        print("  python extract_from_json.py schema <relative_path>")
        print("  python extract_from_json.py names <relative_path>")
        sys.exit(1)

    command = sys.argv[1]

    if command == "extract":
        relative_path = sys.argv[2]
        source = sys.argv[3] if len(sys.argv) > 3 else "XPHB"
        extract_from_json(relative_path, source)
        list_item_names(relative_path)
    elif command == "schema":
        relative_path = sys.argv[2]
        infer_schema(relative_path)
    elif command == "names":
        relative_path = sys.argv[2]
        list_item_names(relative_path)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
