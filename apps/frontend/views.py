from django.shortcuts import render
from django.utils.translation import gettext as _


def index(request):
    return render(request, "frontend/index.html")


def characters_overview(request):
    return render(request, "frontend/overview.html", {"page_title": _("Characters")})


def handbook_overview(request):
    return render(request, "frontend/overview.html", {"page_title": _("Handbook")})


def world_overview(request):
    return render(request, "frontend/overview.html", {"page_title": _("World")})
