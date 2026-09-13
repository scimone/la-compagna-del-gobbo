"""Class and ClassLevel/Subclass lookups (list_classes, get_class, ...)."""

from django.shortcuts import get_object_or_404

from apps.rules.models import ChoiceDefinition, Class, ClassLevel, Subclass


def list_classes():
    return Class.objects.all()


def get_class(class_id: str) -> Class:
    return get_object_or_404(Class, pk=class_id)


def list_class_levels(class_id: str):
    get_class(class_id)
    return ClassLevel.objects.filter(klass_id=class_id)


def list_class_subclasses(class_id: str):
    get_class(class_id)
    return Subclass.objects.filter(klass_id=class_id)


def list_class_choices(class_id: str):
    get_class(class_id)
    return ChoiceDefinition.objects.filter(klass_id=class_id)
