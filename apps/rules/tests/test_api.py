import pytest

from apps.rules.models import Effect, Equipment, EquipmentType


@pytest.mark.django_db
def test_get_class(client, klass):
    response = client.get(f"/api/rules/classes/{klass.pk}")

    assert response.status_code == 200
    assert response.json()["name"] == "Wizard"


@pytest.mark.django_db
def test_get_class_missing_returns_404(client):
    response = client.get("/api/rules/classes/does-not-exist")

    assert response.status_code == 404


@pytest.mark.django_db
def test_list_spells_filters_by_query_params(client, spell):
    response = client.get("/api/rules/spells", {"class": "Wizard", "level": 3})

    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == ["fireball"]


@pytest.mark.django_db
def test_list_equipment_filters_by_category(client):
    melee = EquipmentType.objects.create(id="m", name="Melee Weapon", abbreviation="M")
    Equipment.objects.create(id="dagger", name="Dagger", page=1, srd=True, type=melee)

    response = client.get("/api/rules/equipment", {"category": "Melee Weapon"})

    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == ["dagger"]


@pytest.mark.django_db
def test_list_feature_effects(client, feature):
    Effect.objects.create(feature=feature, tag="dc", raw="{@dc 8}")

    response = client.get(f"/api/rules/features/{feature.pk}/effects")

    assert response.status_code == 200
    assert response.json()[0]["tag"] == "dc"
