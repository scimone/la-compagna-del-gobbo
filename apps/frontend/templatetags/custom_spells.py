import json

from django import template
from django.urls import reverse

from apps.characters.services import play
from apps.rules.models import Spell

register = template.Library()


@register.inclusion_tag("frontend/characters/_spells_editor.html")
def spells_editor(spells_json: str = "", hint: str = "") -> dict:
    """The "spells this grants" field of a custom item or feature (`static/js/item_form.js`): the
    chosen spells as chips, each with how it may be cast for free, and a button that opens the
    spell list (`spell_picker`) to choose more. `spells_json` is what the field starts with."""
    try:
        chosen = play.spell_entries(json.loads(spells_json or "[]"))
    except ValueError:
        chosen = []
    names = dict(Spell.objects.filter(pk__in=[e["id"] for e in chosen]).values_list("pk", "name"))
    return {
        "hint": hint,
        "value": json.dumps(chosen) if chosen else "",
        "names": json.dumps(names).replace("<", "\\u003c"),
        "picker_url": reverse("spell-picker"),
    }
