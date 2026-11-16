from uuid import uuid4

from django import template

from apps.rules.models import Spell

register = template.Library()


@register.inclusion_tag("frontend/characters/_spells_editor.html")
def spells_editor(spells_json: str = "", hint: str = "") -> dict:
    """The "spells this grants" picker of a custom item or feature (`static/js/item_form.js`):
    every spell, by name in the active language, for a search box, and the ids it starts with."""
    spells = Spell.objects.order_by("name")
    return {
        "uid": uuid4().hex[:8],
        "hint": hint,
        "value": spells_json or "",
        "options": [(s.pk, s.name, s.level) for s in spells],
    }
