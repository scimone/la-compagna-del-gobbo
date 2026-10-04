"""The level-up page: pick the class to advance, make the choices its next level asks for, confirm.

The page is one form (the wizard's "live" pattern): choosing a class, a subclass or a feat re-reads
the page with what is filled in so far (`action=select|refresh` - nothing is saved), and the
"Level up" button (`action=commit`) applies it all at once. The rules are `builder.services
.progression`; this module only reads the form and shows the plan.
"""

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _

from apps.builder.services import progression
from apps.characters.models import Character
from apps.characters.services import access
from apps.frontend.character_views import _decorate, _menu_image_url

_DONE_KEY = "levelup_done_%d"


def _values(post) -> dict[str, list[str]]:
    return {key: post.getlist(key) for key in post if key.startswith("lu.")}


def _owner_character(request, pk) -> Character:
    character = get_object_or_404(Character, pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_edit(
        request.user, character
    ):
        raise Http404
    return character


def _feature_rows(features) -> list[dict]:
    return [{"name": f.name, "url": reverse("world-feature-detail", args=[f.pk])} for f in features]


def character_levelup(request, pk):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('account')}?next={request.get_full_path()}")
    character = _owner_character(request, pk)
    sheet = reverse("character-detail", args=[character.pk])
    if not progression.can_level_up(character):
        return redirect(sheet)

    post = request.method == "POST"
    action = request.POST.get("action", "") if post else ""
    class_id = (request.POST if post else request.GET).get("klass", "")
    options = progression.class_options(character)
    allowed = {o["klass"].id for o in options if o["allowed"]}
    if class_id not in allowed:
        class_id = ""
    # A different class starts its choices afresh.
    values = {} if action == "select" or not class_id else _values(request.POST)

    plan = None
    if class_id:
        if action == "commit":
            try:
                plan = progression.commit(character, class_id, values)
            except ValueError:
                plan = progression.plan(character, class_id, values)
            else:
                request.session[_DONE_KEY % character.pk] = {
                    "lines": plan.summary,
                    "features": [{"name": f.name, "pk": f.pk} for f in plan.features],
                }
                return redirect("character-levelup-done", pk=character.pk)
        else:
            plan = progression.plan(character, class_id, values)
    for section in plan.sections if plan else ():
        _decorate(section.pickers)

    show_issues = bool(plan) and action == "commit"
    total = progression.total_level(character)
    response = render(
        request,
        "frontend/characters/levelup.html",
        {
            "page_title": character.name,
            "back_url": sheet,
            "character": character,
            "step_label": _("Level up to level %(level)d") % {"level": total + 1},
            "total": total,
            "xp_ready": progression.xp_ready(character),
            "options": [
                {
                    "id": o["klass"].id,
                    "name": o["klass"].name,
                    "level": o["level"],
                    "allowed": o["allowed"],
                    "reason": o["reason"],
                    "detail": o["klass"].short_description,
                    "image": _menu_image_url("classes", f"{o['klass'].id}-grey.webp"),
                    "url": reverse("world-class-detail", args=[o["klass"].id]),
                    "selected": o["klass"].id == class_id,
                }
                for o in options
            ],
            "class_id": class_id,
            "plan": plan,
            "features": _feature_rows(plan.features) if plan else [],
            "issues": plan.issues if show_issues else [],
            "issue_paths": {i.path: i.message for i in plan.issues} if show_issues else {},
        },
    )
    add_never_cache_headers(response)
    return response


def character_levelup_done(request, pk):
    character = _owner_character(request, pk)
    done = request.session.pop(_DONE_KEY % character.pk, None)
    if done is None:
        return redirect("character-detail", pk=character.pk)
    response = render(
        request,
        "frontend/characters/levelup_done.html",
        {
            "page_title": character.name,
            "back_url": reverse("character-detail", args=[character.pk]),
            "character": character,
            "level": progression.total_level(character),
            "lines": done["lines"],
            "features": [
                {"name": f["name"], "url": reverse("world-feature-detail", args=[f["pk"]])}
                for f in done["features"]
            ],
            "sheet_url": reverse("character-detail", args=[character.pk]),
            # SRD "Preparing Spells": a level can open a change of the prepared spells - offer to
            # go and make it, rather than leaving the player to find the Spellbook tab.
            "spellbook_url": (
                reverse("character-detail", args=[character.pk]) + "?tab=spellbook"
                if character.spell_changes
                else ""
            ),
        },
    )
    add_never_cache_headers(response)
    return response
