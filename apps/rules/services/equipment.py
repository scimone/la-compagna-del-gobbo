"""Equipment, EquipmentProperty and Mastery lookups (list_equipment, get_equipment, ...)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import Equipment, EquipmentProperty, Mastery


def list_equipment(category: str | None = None):
    qs = Equipment.objects.all()
    if category:
        qs = qs.filter(type__name__iexact=category)
    return qs


def get_equipment(equipment_id: str) -> Equipment:
    return get_object_or_404(Equipment, pk=equipment_id)


def list_equipment_properties():
    return EquipmentProperty.objects.all()


def list_masteries():
    return Mastery.objects.all()
