"""The text of a feature that the character sheet splits into cards (`feature_use.PARTS`): its
options are taken out of the text and replaced by links to their own pages, and an upgrade
(Heightened Focus) lists links to the upgraded options."""

from django.urls import reverse

from apps.characters.services import feature_use


def base_name(feature) -> str:
    return feature.name.split(" (")[0]


def part_url(feature, part_name: str, upgrade=None) -> str:
    url = reverse("world-feature-part", args=[feature.pk, feature_use.slug(part_name)])
    return f"{url}?with={upgrade.pk}" if upgrade is not None else url


def find_part(entries, wanted_slug: str):
    """The named sub-entry of a feature's text whose name slugs to `wanted_slug`, or None."""
    if isinstance(entries, list):
        for e in entries:
            if (found := find_part(e, wanted_slug)) is not None:
                return found
    elif isinstance(entries, dict):
        if entries.get("name") and feature_use.slug(entries["name"]) == wanted_slug:
            return entries
        return find_part(entries.get("entries") or entries.get("items") or [], wanted_slug)
    return None


def _swap(node, slugs: set[str], links: dict, state: dict):
    """`node` with every sub-entry named in `slugs` taken out; the first one is replaced by the
    `links` node."""
    if isinstance(node, list):
        out = []
        for item in node:
            if (
                isinstance(item, dict)
                and item.get("name")
                and feature_use.slug(item["name"]) in slugs
            ):
                if not state["placed"]:
                    out.append(links)
                    state["placed"] = True
                continue
            out.append(_swap(item, slugs, links, state))
        return out
    if isinstance(node, dict):
        copy = dict(node)
        for key in ("entries", "items"):
            if isinstance(copy.get(key), list):
                copy[key] = _swap(copy[key], slugs, links, state)
        return copy
    return node


def entries_for(feature):
    """The feature's text, with its options replaced by links to their pages. A feature that is
    neither split nor an upgrade of split options is returned unchanged."""
    parts = feature_use.parts_for(feature)
    if parts:
        names = [name for name, _spec in parts]
        link_target = None
    else:
        upgrade = feature_use.UPGRADES.get(feature.name_en.split(" (")[0])
        if not upgrade:
            return feature.entries
        names, link_target = list(upgrade[1]), feature
    items = [
        {
            "name": name,
            "url": part_url(feature, name, link_target) if link_target else part_url(feature, name),
        }
        for name in names
    ]
    links = {"type": "partlinks", "items": items}
    state = {"placed": False}
    entries = _swap(feature.entries, {feature_use.slug(n) for n in names}, links, state)
    if not state["placed"]:
        entries = [*entries, links] if isinstance(entries, list) else [entries, links]
    return entries
