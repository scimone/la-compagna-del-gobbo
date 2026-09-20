"""The Characters menu: the list, the creation wizard, and the finished character's page.

Views only translate between HTTP and `apps.builder.services` - every rule (what may be chosen,
what a choice grants, what is still missing) lives there. A wizard step is a function that handles
its POST, then returns the context for its template (or a redirect). See
`docs/character_creation_plan.md` section 5.
"""

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.builder import tables
from apps.builder.resolvers import equipment as equipment_resolver
from apps.builder.services import (
    abilities,
    class_choices,
    creation,
    derived_stats,
    origins,
    validation,
)
from apps.builder.services.store import STEPS, Draft, read_values
from apps.characters.models import Character
from apps.characters.services import access
from apps.frontend import units
from apps.frontend.views import (
    _BACKGROUND_IMAGE_SLUGS,
    _SPECIES_IMAGE_SLUGS,
    _menu_image_url,
)
from apps.rules.models import Ability, Background, Class, Equipment, Skill, Species

STEP_LABELS = {
    "class": gettext_lazy("Class"),
    "background": gettext_lazy("Background"),
    "species": gettext_lazy("Species"),
    "languages": gettext_lazy("Languages"),
    "equipment": gettext_lazy("Equipment"),
    "abilities": gettext_lazy("Ability scores"),
    "choices": gettext_lazy("Class features"),
    "alignment": gettext_lazy("Alignment"),
    "details": gettext_lazy("Details"),
    "review": gettext_lazy("Review"),
}
BACKSTORY_QUESTIONS = (
    gettext_lazy("Who is your family?"),
    gettext_lazy("Who was your closest childhood friend?"),
    gettext_lazy("Did you grow up with a pet?"),
    gettext_lazy("Are you in a romantic relationship? If so, with whom?"),
    gettext_lazy(
        "Do you belong to an organization, such as a guild or a religion? Are you still a member?"
    ),
    gettext_lazy("What in your past inspired you to live a life of adventure?"),
)


def _step_url(character: Character, step: str) -> str:
    return reverse("character-wizard", args=[character.pk, step])


def _sign_in_redirect(request):
    return redirect(f"{reverse('account')}?next={request.get_full_path()}")


# --- list --------------------------------------------------------------------------------------


def characters_list(request):
    """Every finished character of every account, plus the viewer's own unfinished ones."""
    finished = Character.objects.filter(status=Character.STATUS_COMPLETE).select_related(
        "owner", "species"
    )
    drafts = (
        Character.objects.filter(status=Character.STATUS_DRAFT, owner=request.user)
        if request.user.is_authenticated
        else Character.objects.none()
    )
    items = [_summary(c) for c in finished if access.can_view(request.user, c)]
    response = render(
        request,
        "frontend/characters/list.html",
        {
            "page_title": _("Characters"),
            "drafts": [
                {"character": c, "url": _step_url(c, creation.get_state(c)["current"])}
                for c in drafts
            ],
            "characters": items,
            "new_id": request.GET.get("new"),
        },
    )
    add_never_cache_headers(response)
    return response


def _summary(character: Character) -> dict:
    classes = ", ".join(
        f"{c.klass.name} {c.level}" for c in character.classes.select_related("klass")
    )
    return {
        "character": character,
        "url": reverse("character-detail", args=[character.pk]),
        "detail": " · ".join(
            x for x in (character.species.name if character.species else "", classes) if x
        ),
        "owner": character.owner.get_username() if character.owner else "",
    }


def character_new(request):
    """Ask for a name, then start a draft and drop the player into the first step."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    if request.method == "POST":
        character = creation.start_draft(request.user, request.POST.get("name", ""))
        return redirect(_step_url(character, "class"))
    return render(
        request,
        "frontend/characters/new.html",
        {"page_title": _("New character"), "back_url": reverse("characters-overview")},
    )


# --- wizard ------------------------------------------------------------------------------------


def _editable_draft(request, pk):
    """`(character, None)` for a draft the viewer owns, else `(None, response)`."""
    character = get_object_or_404(Character, pk=pk)
    if not request.user.is_authenticated:
        return None, _sign_in_redirect(request)
    if character.status == Character.STATUS_COMPLETE:
        return None, redirect("character-detail", pk=pk)
    if not access.can_edit(request.user, character):
        raise Http404
    return character, None


def _next_step(step: str) -> str:
    return STEPS[min(STEPS.index(step) + 1, len(STEPS) - 1)]


def _advance(character: Character, step: str):
    return redirect(_step_url(character, _next_step(step)))


def _issues_context(issues) -> dict:
    return {"issues": issues, "issue_paths": {i.path: i.message for i in issues if i.path}}


def wizard(request, pk, step):
    character, response = _editable_draft(request, pk)
    if response:
        return response
    if step not in STEPS:
        raise Http404
    draft = Draft(character)
    if validation.locked(draft, step):
        missing = next(
            n for n in validation.PREREQUISITES[step] if not validation._chosen(draft, n)
        )
        return redirect(_step_url(character, missing))

    result = _HANDLERS[step](request, character)
    if isinstance(result, HttpResponse):
        return result

    character.refresh_from_db()
    state = creation.get_state(character)
    previous = STEPS[STEPS.index(step) - 1] if STEPS.index(step) else None
    steps = [
        {
            "key": s["key"],
            "label": STEP_LABELS[s["key"]],
            "status": s["status"],
            "url": None if s["status"] == "locked" else _step_url(character, s["key"]),
            "current": s["key"] == step,
        }
        for s in state["steps"]
    ]
    response = render(
        request,
        f"frontend/characters/steps/{step}.html",
        {
            "page_title": character.name,
            "back_url": _step_url(character, previous)
            if previous
            else reverse("characters-overview"),
            "character": character,
            "step": step,
            "step_label": STEP_LABELS[step],
            "steps": steps,
            "state": state,
            "next_url": _step_url(character, _next_step(step)),
            "warnings": state["warnings"],
            **result,
        },
    )
    add_never_cache_headers(response)
    return response


@require_POST
def wizard_finish(request, pk):
    character, response = _editable_draft(request, pk)
    if response:
        return response
    problems = creation.finalize(character)
    if problems:
        return redirect(_step_url(character, creation.get_state(character)["current"]))
    return redirect(f"{reverse('characters-overview')}?new={character.pk}")


@require_POST
def wizard_discard(request, pk):
    character, response = _editable_draft(request, pk)
    if response:
        return response
    creation.discard(character)
    return redirect("characters-overview")


# --- step handlers -----------------------------------------------------------------------------


def _class_step(request, character):
    problems = []
    if request.method == "POST":
        problems = origins.select_class(character, request.POST.get("class", ""))
        if not problems:
            return _advance(character, "class")
    current = Draft(character).klass
    options = [
        {
            "id": c.id,
            "name": c.name,
            "detail": c.short_description,
            "facts": c.primary_ability_display,
            "image": _menu_image_url("classes", f"{c.id}-grey.png"),
            "url": reverse("world-class-detail", args=[c.id]),
            "selected": bool(current and current.id == c.id),
        }
        for c in Class.objects.all()
    ]
    return {"field": "class", "options": options, **_issues_context(problems)}


def _pickers_step(request, character, *, step, choose, options_for, pickers_for, save, image=None):
    """Steps that pick one catalog row (background, species) and then answer its sub-choices.

    Choosing a different row saves it and re-renders (its sub-choices depend on it); submitting
    with the same row saves the sub-choices and moves on once nothing is missing.
    """
    problems = []
    if request.method == "POST":
        current = getattr(Draft(character), step)
        posted = request.POST.get(step, "")
        if posted and (current is None or current.id != posted):
            problems = choose(character, posted)
        elif current is not None:
            pickers = pickers_for(Draft(character))
            problems = save(character, read_values(pickers, request.POST.getlist))
            if not problems:
                return _advance(character, step)
    draft = Draft(character)
    current = getattr(draft, step)
    return {
        "field": step,
        "options": options_for(current),
        "pickers": pickers_for(draft),
        **_issues_context(problems),
    }


def _background_options(current):
    return [
        {
            "id": b.id,
            "name": b.name,
            "detail": b.short_description,
            "facts": ", ".join(s.name for s in b.skills.all()),
            "image": _menu_image_url(
                "backgrounds", f"{_BACKGROUND_IMAGE_SLUGS.get(b.id, b.id)}.jpeg"
            ),
            "url": reverse("world-background-detail", args=[b.id]),
            "selected": bool(current and current.id == b.id),
        }
        for b in Background.objects.prefetch_related("skills")
    ]


def _species_options(current):
    return [
        {
            "id": s.id,
            "name": s.name,
            "detail": s.short_description,
            "facts": "",
            "image": _menu_image_url("species", f"{_SPECIES_IMAGE_SLUGS.get(s.id, s.id)}-grey.png"),
            "url": reverse("world-species-detail", args=[s.id]),
            "selected": bool(current and current.id == s.id),
        }
        for s in Species.objects.filter(hidden=False)
    ]


def _background_step(request, character):
    def save(character, values):
        return origins.save_background_choices(
            character, tool=values.get("background.tool", ""), feat=values.get("background.feat")
        )

    return _pickers_step(
        request,
        character,
        step="background",
        choose=origins.select_background,
        options_for=_background_options,
        pickers_for=origins.background_pickers,
        save=save,
    )


def _species_step(request, character):
    def save(character, values):
        return origins.save_species_choices(
            character, **{k.removeprefix("species."): v for k, v in values.items()}
        )

    return _pickers_step(
        request,
        character,
        step="species",
        choose=origins.select_species,
        options_for=_species_options,
        pickers_for=origins.species_pickers,
        save=save,
    )


def _languages_step(request, character):
    problems = []
    if request.method == "POST":
        if request.POST.get("action") == "roll":
            origins.roll_languages(character)
        else:
            problems = origins.save_languages(character, request.POST.getlist("languages"))
            if not problems:
                return _advance(character, "languages")
    draft = Draft(character)
    return {
        "languages": origins.language_choices(),
        "selected": draft.get("languages", []),
        "count": tables.EXTRA_LANGUAGES_AT_CREATION,
        **_issues_context(problems),
    }


def _gold_label(copper: int) -> str:
    coins = equipment_resolver.split_coins(copper)
    parts = [
        _("%(n)d gp") % {"n": coins["gold"]} if coins["gold"] else "",
        _("%(n)d sp") % {"n": coins["silver"]} if coins["silver"] else "",
        _("%(n)d cp") % {"n": coins["copper"]} if coins["copper"] else "",
    ]
    return " ".join(p for p in parts if p) or _("0 gp")


def _equipment_sources(draft: Draft) -> list[dict]:
    groups = draft.get("equipment.groups", {})
    sources = []
    for source in equipment_resolver.SOURCES:
        obj = equipment_resolver.source_object(draft, source)
        chosen = draft.get(f"equipment.{source}")
        options = []
        for letter, rows in equipment_resolver.option_rows(obj).items():
            lines = []
            for row in rows:
                if row.gold_value is not None:
                    lines.append({"kind": "gold", "text": _gold_label(row.gold_value)})
                elif row.group_id:
                    key = equipment_resolver.group_key(source, row.group_id)
                    lines.append(
                        {
                            "kind": "group",
                            "field": f"group.{key}",
                            "group": row.group,
                            "choices": row.group.items.all(),
                            "selected": groups.get(key, ""),
                        }
                    )
                else:
                    lines.append(
                        {
                            "kind": "item",
                            "item": row.item,
                            "quantity": row.quantity,
                            "contents": [
                                (c.item, c.quantity)
                                for c in row.item.pack_content_rows.select_related("item")
                            ],
                        }
                    )
            options.append({"letter": letter, "lines": lines, "selected": letter == chosen})
        sources.append(
            {"key": source, "label": obj.name, "options": options, "field": f"equipment.{source}"}
        )
    return sources


def _equipment_step(request, character):
    problems = []
    if request.method == "POST":
        groups = {
            name.removeprefix("group."): value
            for name, value in request.POST.items()
            if name.startswith("group.") and value
        }
        problems = origins.save_equipment(
            character,
            class_option=request.POST.get("equipment.class", ""),
            background_option=request.POST.get("equipment.background", ""),
            groups=groups,
        )
        if not problems:
            return _advance(character, "equipment")
    return {"sources": _equipment_sources(Draft(character)), **_issues_context(problems)}


def _int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _abilities_step(request, character):
    problems = []
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "method":
            abilities.set_method(character, request.POST.get("method", ""))
        elif action == "roll":
            abilities.set_method(character, "roll")
            abilities.roll_scores(character)
        elif action == "suggest":
            abilities.suggest_standard_array(character)
        else:
            base = {a: _int(request.POST.get(f"base.{a}")) for a in tables.ABILITIES}
            bonus = {a: _int(request.POST.get(f"bonus.{a}")) or 0 for a in tables.ABILITIES}
            base = {a: v for a, v in base.items() if v is not None}
            problems = abilities.save(
                character,
                method=request.POST.get("method")
                or (Draft(character).get("abilities") or {}).get("method", ""),
                base=base,
                bonus=bonus,
            )
            if not problems:
                return _advance(character, "abilities")
    draft = Draft(character)
    options = abilities.options(draft)
    state = draft.get("abilities") or {}
    names = {a.id: a.name for a in Ability.objects.all()}
    primary = {a.id for a in draft.klass.primary_abilities.all()}
    rows = [
        {
            "id": a,
            "name": names.get(a, a),
            "base": (state.get("base") or {}).get(a, ""),
            "bonus": (state.get("bonus") or {}).get(a, 0),
            "bonus_allowed": a in options["bonus_from"],
            "final": options["final"][a],
            "modifier": tables.ability_modifier(options["final"][a]),
            "primary": a in primary,
        }
        for a in tables.ABILITIES
    ]
    method = state.get("method", "")
    spent = None
    if (
        method == "pointbuy"
        and rows
        and all(str(r["base"]).isdigit() and int(r["base"]) in tables.POINT_BUY_COST for r in rows)
    ):
        spent = sum(tables.POINT_BUY_COST[int(r["base"])] for r in rows)
    return {
        "method": method,
        "method_labels": [
            ("standard", _("Standard array")),
            ("roll", _("Roll")),
            ("pointbuy", _("Point buy")),
        ],
        "options": options,
        "rows": rows,
        "spent": spent,
        "value_choices": {
            "standard": list(tables.STANDARD_ARRAY),
            "roll": sorted(options["rolled"] or [], reverse=True),
            "pointbuy": list(tables.POINT_BUY_COST),
        }.get(method, []),
        **_issues_context(problems),
    }


def _choices_step(request, character):
    problems = []
    if request.method == "POST":
        pickers = class_choices.pickers(Draft(character))
        values = read_values(pickers, request.POST.getlist)
        problems = class_choices.save(
            character, **{k.removeprefix("class."): v for k, v in values.items()}
        )
        if not problems:
            return _advance(character, "choices")
    return {"pickers": class_choices.pickers(Draft(character)), **_issues_context(problems)}


def _alignment_step(request, character):
    problems = []
    if request.method == "POST":
        problems = origins.save_alignment(character, request.POST.get("alignment", ""))
        if not problems:
            return _advance(character, "alignment")
    character.refresh_from_db()
    return {
        "alignments": [(code, name, abbr) for code, name, abbr in tables.ALIGNMENTS],
        "selected": character.alignment,
        **_issues_context(problems),
    }


def _details_step(request, character):
    if request.method == "POST":
        backstory = {
            str(i): request.POST.get(f"backstory.{i}", "").strip()
            for i in range(len(BACKSTORY_QUESTIONS))
        }
        creation.save_details(
            character,
            appearance=request.POST.get("appearance", ""),
            notes=request.POST.get("notes", ""),
            backstory=backstory,
        )
        return _advance(character, "details")
    character.refresh_from_db()
    saved = (Draft(character).get("details") or {}).get("backstory", {})
    return {
        "questions": [
            (str(i), q, saved.get(str(i), "")) for i, q in enumerate(BACKSTORY_QUESTIONS)
        ],
    }


def _review_step(request, character):
    problems = []
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "reset":
            creation.reset_manual(character)
        elif action == "adjust":
            scores = {a: _int(request.POST.get(f"score.{a}")) for a in tables.ABILITIES}
            problems = creation.set_manual_abilities(
                character, {a: v for a, v in scores.items() if v is not None}
            )
            states = {s.id: request.POST.get(f"skill.{s.id}", "none") for s in Skill.objects.all()}
            problems += creation.set_manual_skills(character, states)
    character.refresh_from_db()
    return {**_review_context(character), **_issues_context(problems)}


_WARNING_TEXTS = {
    "strength_requirement": gettext_lazy(
        "Your Strength is below this armor's requirement: your speed is reduced by 10 ft."
    ),
    "stealth_disadvantage": gettext_lazy(
        "This armor gives you disadvantage on Dexterity (Stealth) checks."
    ),
}


def _warning_text(code: str) -> str:
    if code.startswith("not_proficient:"):
        return _(
            "You are not trained with %(kind)s armor: disadvantage on Strength and Dexterity "
            "d20 tests, and you can't cast spells."
        ) % {"kind": code.split(":", 1)[1]}
    return str(_WARNING_TEXTS.get(code, code))


def _review_context(character: Character) -> dict:
    """Everything the Review step and a finished character's page show, computed from rows."""
    stats = derived_stats.compute(character)
    draft = Draft(character)
    manual_scores = draft.get("manual.abilities") or {}
    manual_skills = draft.get("manual.skills") or {}
    names = {a.id: a.name for a in Ability.objects.all()}
    equipment_names = {
        e.id: e.name
        for e in Equipment.objects.filter(
            id__in=[a["equipment_id"] for a in stats.attacks]
            + [stats.armor_class["armor_id"] or ""]
        )
    }
    items = list(character.inventory_items.select_related("equipment").order_by("pk"))
    children: dict[int, list] = {}
    for item in items:
        if item.parent_id:
            children.setdefault(item.parent_id, []).append(item)
    ac = stats.armor_class
    if ac["armor_id"]:
        ac_label = equipment_names.get(ac["armor_id"], "")
    elif ac["formula"].startswith("unarmored defense"):
        ac_label = _("Unarmored Defense")
    else:
        ac_label = _("No armor")
    return {
        "stats": stats,
        "speed_label": units.distance(stats.speed),
        "ac_label": ac_label,
        "warning_texts": [_warning_text(w) for w in stats.warnings],
        "ability_rows": [
            {
                "id": a,
                "name": names.get(a, a),
                **stats.abilities[a],
                "manual": a in manual_scores,
                "save": stats.saving_throws[a],
            }
            for a in tables.ABILITIES
        ],
        "skill_rows": [
            {
                "id": s.id,
                "name": s.name,
                "ability": names.get(s.ability_id, ""),
                **stats.skills[s.id],
                "manual": s.id in manual_skills,
            }
            for s in Skill.objects.select_related("ability").order_by("name")
        ],
        "attack_rows": [
            {**a, "name": equipment_names.get(a["equipment_id"], a["equipment_id"])}
            for a in stats.attacks
        ],
        "outstanding": validation.validate(draft),
        "has_manual": bool(manual_scores or manual_skills),
        "score_range": tables.MANUAL_SCORE_RANGE,
        "inventory": [(i, children.get(i.pk, [])) for i in items if i.parent_id is None],
        "languages": [cl.language for cl in character.languages.select_related("language")],
        "senses": list(character.senses.select_related("sense")),
        "features": [cf.feature for cf in character.features.select_related("feature")],
        "feats": list(character.feats.select_related("feat")),
        "spells": list(
            character.spells.select_related("spell", "klass").order_by(
                "spell__level", "spell__name"
            )
        ),
        "resources": list(character.resources.all()),
        "coins": character.currency if hasattr(character, "currency") else None,
    }


_HANDLERS = {
    "class": _class_step,
    "background": _background_step,
    "species": _species_step,
    "languages": _languages_step,
    "equipment": _equipment_step,
    "abilities": _abilities_step,
    "choices": _choices_step,
    "alignment": _alignment_step,
    "details": _details_step,
    "review": _review_step,
}


# --- a character's page ------------------------------------------------------------------------


def character_detail(request, pk):
    character = get_object_or_404(Character, pk=pk)
    if not access.can_view(request.user, character):
        raise Http404
    if character.status == Character.STATUS_DRAFT:
        return redirect(_step_url(character, creation.get_state(character)["current"]))
    response = render(
        request,
        "frontend/characters/detail.html",
        {
            "page_title": character.name,
            "back_url": reverse("characters-overview"),
            "character": character,
            "can_edit": access.can_edit(request.user, character),
            "alignment_name": next(
                (name for code, name, _abbr in tables.ALIGNMENTS if code == character.alignment), ""
            ),
            **_review_context(character),
        },
    )
    add_never_cache_headers(response)
    return response
