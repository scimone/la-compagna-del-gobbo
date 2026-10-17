"""The Characters menu: the list and the creation wizard.

A finished character's page is `character_sheet`.

Views only translate between HTTP and `apps.builder.services` - every rule (what may be chosen,
what a choice grants, what is still missing) lives there. A wizard step is a function that handles
its POST, then returns the context for its template (or a redirect). See
`docs/character_creation_plan.md` section 5.
"""

from django.http import Http404, HttpResponse, HttpResponseForbidden
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
    progression,
    validation,
)
from apps.builder.services.store import STEPS, Draft, read_values
from apps.campaigns.services import membership
from apps.characters.models import Character
from apps.characters.services import access
from apps.characters.services import character as character_service
from apps.frontend import accounts, campaign_context, campaign_views, translations, units
from apps.frontend.entries_render import render_entries
from apps.frontend.views import (
    _BACKGROUND_IMAGE_SLUGS,
    _SCHOOL_LABELS,
    _SPECIES_IMAGE_SLUGS,
    _WEAPON_CATEGORY_LABELS,
    _format_casting_time,
    _format_components,
    _format_duration,
    _format_feat_ability,
    _format_feat_category,
    _format_option_prerequisite,
    _format_prerequisite,
    _format_range,
    _menu_image_url,
    _pick_translation,
)
from apps.rules.models import (
    Ability,
    Background,
    Class,
    Equipment,
    Feat,
    Feature,
    Mastery,
    OptionalFeature,
    Skill,
    Species,
    Spell,
)

STEP_LABELS = {
    "class": gettext_lazy("Class"),
    "background": gettext_lazy("Background"),
    "species": gettext_lazy("Species"),
    "languages": gettext_lazy("Languages"),
    "equipment": gettext_lazy("Equipment"),
    "abilities": gettext_lazy("Ability scores"),
    "alignment": gettext_lazy("Alignment"),
    "story": gettext_lazy("Background story"),
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
    """Every finished character of the current campaign, plus the viewer's own unfinished ones
    (the campaign's DM and administrators see everyone's)."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = campaign_context.current(request)
    if campaign is None:
        return campaign_views.no_campaign_page(request, _("Characters"))
    finished = Character.objects.filter(
        campaign=campaign, status=Character.STATUS_COMPLETE
    ).select_related("owner", "species")
    drafts = Character.objects.filter(campaign=campaign, status=Character.STATUS_DRAFT)
    if not membership.can_manage(request.user, campaign):
        drafts = drafts.filter(owner=request.user)
    items = [
        _summary(c, access.can_edit(request.user, c))
        for c in finished
        if access.can_view(request.user, c)
    ]
    response = render(
        request,
        "frontend/characters/list.html",
        {
            "page_title": _("Characters"),
            "can_create": membership.is_member(request.user, campaign),
            "drafts": [
                {
                    "character": c,
                    "url": _step_url(c, creation.get_state(c)["current"]),
                    "owner": accounts.display_name(c.owner)
                    if c.owner_id != request.user.id
                    else "",
                }
                for c in drafts
            ],
            "characters": items,
            "new_id": request.GET.get("new"),
            "view_mode": _view_mode(request),
        },
    )
    add_never_cache_headers(response)
    return response


def _view_mode(request) -> str:
    """`grid` (large square pictures, the default) or `list` - chosen with `?view=` and then
    remembered for the session."""
    chosen = request.GET.get("view")
    if chosen in ("grid", "list"):
        request.session["characters_view"] = chosen
    return request.session.get("characters_view", "grid")


def _summary(character: Character, can_delete: bool = False) -> dict:
    classes = [
        f"{c.klass.name} · {_('Level')} {c.level}"
        for c in character.classes.select_related("klass")
    ]
    return {
        "character": character,
        "url": reverse("character-detail", args=[character.pk]),
        "detail": " · ".join(
            x for x in (character.species.name if character.species else "", *classes) if x
        ),
        "owner": accounts.display_name(character.owner) if character.owner else "",
        "can_delete": can_delete,
        # Only the owner's own list shows it, and only once the XP reach the next level.
        "level_up_url": (
            reverse("character-levelup", args=[character.pk])
            if can_delete and progression.xp_ready(character)
            else ""
        ),
        "portrait": (
            f"{reverse('character-portrait', args=[character.pk])}?v={character.portrait.name}"
            if character.portrait
            else ""
        ),
        "avatar": (
            f"{reverse('character-avatar', args=[character.pk])}?v={character.portrait.name}-"
            f"{character.portrait_cx:.4f}-{character.portrait_cy:.4f}-{character.portrait_zoom:.3f}"
            if character.portrait
            else ""
        ),
    }


def character_new(request):
    """Ask for a name, then start a draft in the current campaign and drop the player into the
    first step. Any member of the campaign creates characters."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = campaign_context.current(request)
    if campaign is None or not membership.is_member(request.user, campaign):
        raise Http404
    if request.method == "POST":
        character = creation.start_draft(request.user, request.POST.get("name", ""), campaign)
        return redirect(_step_url(character, "background"))
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
            "editing": creation.is_editing(character),
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
    editing = creation.is_editing(character)
    problems = creation.finalize(character)
    if problems:
        return redirect(_step_url(character, creation.get_state(character)["current"]))
    if editing:
        return redirect("character-detail", pk=character.pk)
    return redirect(f"{reverse('characters-overview')}?new={character.pk}")


@require_POST
def wizard_discard(request, pk):
    character, response = _editable_draft(request, pk)
    if response:
        return response
    creation.discard(character)
    return redirect("characters-overview")


@require_POST
def character_reopen(request, pk):
    """Its owner, the campaign's DM or an admin: turn a finished level-1 character back into a
    draft and open the wizard."""
    character = get_object_or_404(Character, pk=pk)
    if not access.can_edit(request.user, character):
        return HttpResponseForbidden()
    if not creation.reopen(character):
        return redirect("character-detail", pk=pk)
    return redirect(_step_url(character, creation.get_state(character)["current"]))


@require_POST
def character_delete(request, pk):
    """Delete a finished character (only its owner may)."""
    character = get_object_or_404(Character, pk=pk)
    if not access.can_edit(request.user, character):
        return HttpResponseForbidden()
    character_service.delete_character(character.pk)
    return redirect("characters-overview")


def character_assign(request, pk):
    """The campaign's DM or an admin: choose which member a character belongs to."""
    character = get_object_or_404(Character, pk=pk)
    if not membership.can_manage(request.user, character.campaign):
        raise Http404
    users = [m.user for m in membership.members(character.campaign)]
    if request.method == "POST":
        new_owner = next((u for u in users if str(u.pk) == request.POST.get("owner")), None)
        if new_owner is not None:
            character_service.assign_owner(character, new_owner)
            return redirect("character-detail", pk=character.pk)
    return render(
        request,
        "frontend/characters/assign.html",
        {
            "page_title": _("Assign character"),
            "back_url": reverse("character-detail", args=[character.pk]),
            "character": character,
            "owners": [
                {
                    "id": u.pk,
                    "name": accounts.display_name(u),
                    "current": u.pk == character.owner_id,
                }
                for u in users
            ],
        },
    )


# --- step handlers -----------------------------------------------------------------------------


def _pickers_step(request, character, *, step, current_of, choose, options_for, pickers_for, save):
    """A step that picks one catalog row (class, background, species) and answers its choices.

    The choices appear right under the picked row (see `_options.html`). Three kinds of POST:

    - `action=select` (the page's script, when a row is clicked): remember the row; nothing more.
    - `action=refresh` (the script, when an answer changes what other answers offer): save what is
      filled in so far. Neither shows "still missing" messages - the player is mid-answer.
    - the "Save and continue" button: save, and move on once nothing is missing.

    Without the script (or after picking a different row and pressing the button) the same three
    outcomes happen through a full page load.
    """
    problems = []
    if request.method == "POST":
        action = request.POST.get("action", "continue")
        current = current_of(Draft(character))
        posted = request.POST.get(step, "")
        if posted and (current is None or current.id != posted):
            problems = choose(character, posted)  # a different row: its choices start afresh
        elif current is not None:
            pickers = pickers_for(Draft(character))
            problems = save(character, read_values(pickers, request.POST.getlist))
            if action == "continue" and not problems:
                return _advance(character, step)
        if action in ("select", "refresh"):
            problems = []
    draft = Draft(character)
    return {
        "field": step,
        "options": options_for(current_of(draft)),
        "pickers": _decorate(pickers_for(draft)),
        **_issues_context(problems),
    }


def _class_options(current):
    return [
        {
            "id": c.id,
            "name": c.name,
            "detail": c.short_description,
            "facts": c.primary_ability_display,
            "image": _menu_image_url("classes", f"{c.id}-grey.webp"),
            "vignette": False,
            "url": reverse("world-class-detail", args=[c.id]),
            "selected": bool(current and current.id == c.id),
        }
        for c in Class.objects.all()
    ]


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
            "vignette": True,  # the background artwork gets the same soft edge as in the World
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
            "image": _menu_image_url(
                "species", f"{_SPECIES_IMAGE_SLUGS.get(s.id, s.id)}-grey.webp"
            ),
            "vignette": False,
            "url": reverse("world-species-detail", args=[s.id]),
            "selected": bool(current and current.id == s.id),
        }
        for s in Species.objects.filter(hidden=False)
    ]


def _class_step(request, character):
    def save(character, values):
        return class_choices.save(
            character, **{k.removeprefix("class."): v for k, v in values.items()}
        )

    return _pickers_step(
        request,
        character,
        step="class",
        current_of=lambda draft: draft.klass,
        choose=origins.select_class,
        options_for=_class_options,
        pickers_for=class_choices.pickers,
        save=save,
    )


def _background_step(request, character):
    def save(character, values):
        return origins.save_background_choices(
            character, tool=values.get("background.tool", ""), feat=values.get("background.feat")
        )

    return _pickers_step(
        request,
        character,
        step="background",
        current_of=lambda draft: draft.background,
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
        current_of=lambda draft: draft.species,
        choose=origins.select_species,
        options_for=_species_options,
        pickers_for=origins.species_pickers,
        save=save,
    )


# --- catalog cards for pickers -----------------------------------------------------------------
# A picker of spells / tools / feats / ... is shown in the World's list design (icon, name, a line
# of properties) with a "Read" button that unfolds the description. The rows are the same ones the
# World lists show; the properties line is built the same way.

_DAMAGE_TYPE_LABELS = {
    "piercing": ("piercing", "perforanti"),
    "bludgeoning": ("bludgeoning", "contundenti"),
    "slashing": ("slashing", "taglienti"),
    "psychic": ("psychic", "psichici"),
}
_CARD_MODELS = {
    "spell": Spell,
    "equipment": Equipment,
    "feat": Feat,
    "invocation": OptionalFeature,
    "skill": Skill,
}


def _damage_text(item) -> str:
    """`1d8 slashing`, and for a Versatile weapon `1d8 slashing (1d10 two-handed)`. Works on an
    `Equipment` row and a `CharacterCustomItem` alike."""
    kind = _pick_translation(_DAMAGE_TYPE_LABELS, item.damage_type) if item.damage_type else ""
    text = f"{item.damage_dice} {kind}".strip()
    if item.versatile_damage_dice:
        text += f" ({item.versatile_damage_dice} {_('two-handed')})"
    return text


def _card_line(kind: str, obj) -> str:
    """The line of properties under a card's name - the same one the World list rows carry."""
    if kind == "spell":
        level = _("Cantrip") if obj.level == 0 else f"{_('Level')} {obj.level}"
        return f"{level} · {_pick_translation(_SCHOOL_LABELS, obj.school)}"
    if kind == "feat":
        return _format_feat_category(obj.category)
    if kind == "invocation":
        return _("Eldritch Invocation")
    if kind == "skill":
        return obj.ability.name
    parts = [obj.type.name if obj.type_id else ""]
    if obj.weapon_category:
        parts.insert(0, _pick_translation(_WEAPON_CATEGORY_LABELS, obj.weapon_category))
    if obj.damage_dice:
        parts.append(_damage_text(obj))
    if masteries := ", ".join(m.name for m in obj.masteries.all()):
        parts.append(masteries)
    if obj.value:
        parts.append(_gold_label(obj.value))
    return " · ".join(p for p in parts if p)


def _card_image(kind: str, obj) -> str | None:
    if kind == "spell":
        return _menu_image_url("spells", f"{obj.school.lower()}.jpeg")
    if kind == "feat":
        return _menu_image_url(
            "feats", f"{obj.category.split(' (')[0].lower().replace(' ', '_')}.jpeg"
        )
    return None


def _decorate(pickers):
    """Give each catalog picker its `cards` (see the module note above); plain ones need none."""
    for picker in pickers:
        model = _CARD_MODELS.get(picker.kind)
        if model is None:
            picker.cards = None
            continue
        ids = [c[0] for c in picker.candidates]
        queryset = model.objects.filter(id__in=ids)
        if picker.kind == "skill":
            queryset = queryset.select_related("ability")
        elif picker.kind == "equipment":
            queryset = queryset.select_related("type").prefetch_related("masteries")
        objects = queryset.in_bulk()
        picker.cards = [
            {
                "id": ident,
                "name": name,
                "detail": _card_line(picker.kind, objects[ident]),
                "image": _card_image(picker.kind, objects[ident]),
                "describe": reverse("character-describe", args=[picker.kind, ident]),
                "checked": ident in picker.selected,
            }
            for ident, name in picker.candidates
            if ident in objects
        ]
    return pickers


# --- descriptions (unfolded under a card) -------------------------------------------------------


def _describe_spell(pk):
    spell = get_object_or_404(Spell, pk=pk)
    facts = [
        (_("Level"), _("Cantrip") if spell.level == 0 else spell.level),
        (_("School"), _pick_translation(_SCHOOL_LABELS, spell.school)),
        (_("Casting Time"), _format_casting_time(spell.casting_time)),
        (_("Range"), _format_range(spell.range)),
        (_("Components"), _format_components(spell.components)),
        (_("Duration"), _format_duration(spell.duration)),
    ]
    sections = [render_entries(spell.entries)]
    if spell.entries_higher_level:
        sections.append(render_entries(spell.entries_higher_level))
    return facts, sections


def _describe_feat(pk):
    feat = get_object_or_404(Feat, pk=pk)
    facts = [(_("Category"), _format_feat_category(feat.category))]
    if feat.prerequisite:
        facts.append((_("Prerequisite"), _format_prerequisite(feat.prerequisite)))
    if ability := _format_feat_ability(feat.ability):
        facts.append((_("Ability Score Increase"), ability))
    return facts, [render_entries(feat.entries)]


def _describe_invocation(pk):
    feature = get_object_or_404(OptionalFeature, pk=pk)
    facts = []
    if feature.prerequisite:
        facts.append((_("Prerequisite"), _format_option_prerequisite(feature.prerequisite)))
    return facts, [render_entries(feature.entries)]


def _describe_skill(pk):
    skill = get_object_or_404(Skill.objects.select_related("ability"), pk=pk)
    return [(_("Ability"), skill.ability.name)], [render_entries(skill.entries)]


def _describe_equipment(pk):
    item = get_object_or_404(
        Equipment.objects.select_related("type").prefetch_related("properties", "masteries"), pk=pk
    )
    facts = []
    if item.type_id:
        facts.append((_("Type"), item.type.name))
    if item.weapon_category:
        facts.append(
            (_("Category"), _pick_translation(_WEAPON_CATEGORY_LABELS, item.weapon_category))
        )
    if item.damage_dice:
        facts.append((_("Damage"), _damage_text(item)))
    if item.ac:
        facts.append((_("Armor Class"), item.ac))
    property_names = [p.name for p in item.properties.all()]
    if item.range:  # Thrown / Ammunition weapons: the range is one more property
        property_names.append(f"{_('Range')} {units.weapon_range(item.range)}")
    if property_names:
        facts.append((_("Properties"), ", ".join(property_names)))
    if masteries := ", ".join(m.name for m in item.masteries.all()):
        facts.append((_("Mastery"), masteries))
    if item.value:
        facts.append((_("Cost"), _gold_label(item.value)))
    if item.weight:
        facts.append((_("Weight"), units.metricize_text(f"{item.weight:g} lb.")))
    sections = [render_entries(item.entries)] if item.entries else []
    # A weapon has no description of its own: what matters is what its properties and its
    # Mastery mean, so those are spelled out.
    for mastery in item.masteries.all():
        sections.append(
            render_entries([{"type": "entries", "name": mastery.name, "entries": mastery.entries}])
        )
    for prop in item.properties.all():
        sections.append(render_entries(prop.entries))
    return facts, sections


def _describe_feature(pk):
    return [], [render_entries(get_object_or_404(Feature, pk=pk).entries)]


def _describe_mastery(pk):
    mastery = get_object_or_404(Mastery, pk=pk)
    return [], [render_entries(mastery.entries)]


_DESCRIBERS = {
    "feature": _describe_feature,
    "mastery": _describe_mastery,
    "spell": _describe_spell,
    "feat": _describe_feat,
    "invocation": _describe_invocation,
    "skill": _describe_skill,
    "equipment": _describe_equipment,
}


def describe(request, kind, pk):
    """The description of one catalog row, as a fragment the wizard unfolds under its card."""
    describer = _DESCRIBERS.get(kind)
    if describer is None:
        raise Http404
    facts, sections = describer(pk)
    return render(
        request, "frontend/characters/_describe.html", {"facts": facts, "sections": sections}
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


def _story_step(request, character):
    if request.method == "POST":
        before = character.backstory
        creation.save_backstory(character, request.POST.get("backstory", ""))
        if character.backstory != before:
            translations.enqueue("backstory", character.pk, {"backstory": character.backstory})
        return _advance(character, "story")
    return {"questions": BACKSTORY_QUESTIONS, "backstory": character.backstory}


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
        ac_label = ac["armor_name"] or equipment_names.get(ac["armor_id"], "")
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
            {
                **a,
                "name": a["custom_name"]
                or equipment_names.get(a["equipment_id"], a["equipment_id"]),
            }
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
    "alignment": _alignment_step,
    "story": _story_step,
    "review": _review_step,
}
