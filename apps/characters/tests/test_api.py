import pytest


@pytest.mark.django_db
def test_create_get_update_delete_character(client, species, background):
    create_response = client.post(
        "/api/characters/",
        {
            "name": "Aragorn",
            "species_id": species.pk,
            "background_id": background.pk,
            "max_hit_points": 44,
            "current_hit_points": 44,
        },
        content_type="application/json",
    )
    assert create_response.status_code == 200
    character_id = create_response.json()["id"]
    assert create_response.json()["alignment"] == ""

    get_response = client.get(f"/api/characters/{character_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Aragorn"

    patch_response = client.patch(
        f"/api/characters/{character_id}",
        {"alignment": "Lawful Good"},
        content_type="application/json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["alignment"] == "Lawful Good"

    delete_response = client.delete(f"/api/characters/{character_id}")
    assert delete_response.status_code == 200

    assert client.get(f"/api/characters/{character_id}").status_code == 404


@pytest.mark.django_db
def test_inventory_flow(client, character, equipment_item):
    add_response = client.post(
        f"/api/characters/{character.pk}/inventory",
        {"equipment_id": equipment_item.pk, "quantity": 1, "equipped": True},
        content_type="application/json",
    )
    assert add_response.status_code == 200
    item_id = add_response.json()["id"]

    unequip_response = client.post(f"/api/characters/{character.pk}/inventory/{item_id}/unequip")
    assert unequip_response.json()["equipped"] is False

    list_response = client.get(f"/api/characters/{character.pk}/inventory")
    assert len(list_response.json()) == 1

    delete_response = client.delete(f"/api/characters/{character.pk}/inventory/{item_id}")
    assert delete_response.status_code == 200
    assert client.get(f"/api/characters/{character.pk}/inventory").json() == []


@pytest.mark.django_db
def test_spell_flow(client, character, spell):
    add_response = client.post(
        f"/api/characters/{character.pk}/spells",
        {"spell_id": spell.pk, "prepared": True},
        content_type="application/json",
    )
    assert add_response.status_code == 200
    assert add_response.json()["prepared"] is True

    unprepare_response = client.post(f"/api/characters/{character.pk}/spells/{spell.pk}/unprepare")
    assert unprepare_response.json()["prepared"] is False

    remove_response = client.delete(f"/api/characters/{character.pk}/spells/{spell.pk}")
    assert remove_response.status_code == 200


@pytest.mark.django_db
def test_currency_flow(client, character):
    get_response = client.get(f"/api/characters/{character.pk}/currency")
    assert get_response.json()["gold"] == 0

    patch_response = client.patch(
        f"/api/characters/{character.pk}/currency",
        {"gold": 15},
        content_type="application/json",
    )
    assert patch_response.json()["gold"] == 15


@pytest.mark.django_db
def test_sheet_and_empty_details_endpoints(client, character):
    sheet_response = client.get(f"/api/characters/{character.pk}/sheet")
    assert sheet_response.status_code == 200
    body = sheet_response.json()
    assert body["character"]["id"] == character.pk
    assert body["currency"] is None

    for endpoint in [
        "classes",
        "feats",
        "features",
        "languages",
        "optional-features",
        "proficiencies",
        "senses",
        "resources",
        "choices",
    ]:
        response = client.get(f"/api/characters/{character.pk}/{endpoint}")
        assert response.status_code == 200, endpoint
        assert response.json() == []
