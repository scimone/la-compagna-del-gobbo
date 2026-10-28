"""The builder must offer the same choices in Italian as in English.

Rules data is stored with an English and an Italian column and `name` reads the active language;
code that compares those against English constants (class names in `Spell.classes`, "Subclass"
markers, ...) silently finds nothing in Italian. Every class is levelled 1 -> 20 and the plan of
each step is compared between the two languages.
"""

import pytest
from django.utils import translation

from apps.builder.services import progression
from apps.builder.tests.test_progression import CLASS_IDS, autofill, finished, level_up

pytestmark = pytest.mark.usefixtures("imported_rules")


def signature(plan):
    return {
        "pickers": {p.key: (p.count, len(p.candidates)) for s in plan.sections for p in s.pickers},
        "features": sorted(f.name_en for f in plan.features),
        "sections": [s.key for s in plan.sections],
    }


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_every_level_up_asks_the_same_in_italian(owner, class_id):
    character = finished(owner, class_id)
    for _level in range(2, 21):
        values = autofill(character, class_id)
        english = signature(progression.plan(character, class_id, values))
        with translation.override("it"):
            italian = signature(progression.plan(character, class_id, values))
        assert italian == english
        level_up(character, class_id)


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_creation_pickers_are_the_same_in_italian(owner, class_id):
    from apps.builder.services import class_choices
    from apps.builder.services.store import Draft
    from apps.builder.tests.conftest import build_character

    character = build_character(owner, class_id)

    def pickers():
        return {
            p.key: (p.count, len(p.candidates)) for p in class_choices.pickers(Draft(character))
        }

    english = pickers()
    with translation.override("it"):
        assert pickers() == english


@pytest.mark.parametrize("class_id", CLASS_IDS)
def test_sheet_and_level_up_pages_render_in_italian(client, owner, class_id):
    character = finished(owner, class_id)
    for _level in range(3):
        level_up(character, class_id)
    client.force_login(owner)
    for language in ("en", "it"):
        client.cookies["django_language"] = language
        for url in (f"/characters/{character.pk}/", f"/characters/{character.pk}/levelup/"):
            response = client.get(url, follow=True)
            assert response.status_code == 200, (language, url)
