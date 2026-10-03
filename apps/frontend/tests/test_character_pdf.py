"""The "Export to PDF" menu item: a finished character written into the official sheet."""

from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from pypdf import PdfReader

from apps.builder.tests.conftest import build_character
from apps.characters.models import Character
from apps.frontend.tests.test_character_sheet import finished

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def signed_in(client, alice):
    client.force_login(alice)
    return client


def fields(response) -> dict:
    assert response.status_code == 200
    return {k: v.get("/V") for k, v in PdfReader(BytesIO(response.content)).get_fields().items()}


def test_sheet_has_a_menu_with_the_export_link(signed_in, alice):
    cleric = finished(alice, "cleric")
    html = signed_in.get(f"/characters/{cleric.pk}/").content.decode()
    assert f'href="/characters/{cleric.pk}/export-pdf/"' in html


def test_export_downloads_a_pdf(signed_in, alice):
    cleric = finished(alice, "cleric", name="Bruno Il Forte")
    response = signed_in.get(f"/characters/{cleric.pk}/export-pdf/")
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'attachment; filename="bruno-il-forte.pdf"'
    assert response.content.startswith(b"%PDF")
    # The template's own source file is not shipped along with every download.
    assert len(response.content) < 12_000_000


def test_export_writes_the_character_into_the_sheet(signed_in, alice):
    cleric = finished(alice, "cleric", name="Bruno")
    cleric.strength = 8
    cleric.experience_points = 0
    cleric.inspiration = True
    cleric.save()
    values = fields(signed_in.get(f"/characters/{cleric.pk}/export-pdf/"))
    assert values["Text Box 1"] == "Bruno"
    assert values["Text Box 3"] == "Cleric"
    assert values["Level"] == "1"
    assert values["Numeric Field 3"] == "8"  # Strength score
    assert values["Strength Mod"] == "-1"
    assert values["Max HP"] == str(cleric.max_hit_points)
    assert values["Inspiration"] == "/Yes"
    assert values["Check Box 12"] == "/Yes"  # trained with light armor and shields
    assert values["Check Box 10"] == "/Yes"


def test_export_fills_the_spell_table_and_slots(signed_in, alice):
    cleric = finished(alice, "cleric")
    values = fields(signed_in.get(f"/characters/{cleric.pk}/export-pdf/"))
    spell_names = [v for k, v in values.items() if k.startswith("Spell Name.") and v]
    assert spell_names  # a level 1 cleric knows cantrips
    assert values["Spell Level.0.0"] == "2"  # two level 1 slots
    assert values["Spellcasting.1"] not in (None, "")  # spell save DC
    # No row keeps the template's placeholder text.
    assert "Spell Name" not in values.values()


def test_export_of_a_draft_is_not_found(signed_in, alice):
    draft = build_character(alice, "cleric", "acolyte", "human", "Draft")
    assert draft.status == Character.STATUS_DRAFT
    assert signed_in.get(f"/characters/{draft.pk}/export-pdf/").status_code == 404
