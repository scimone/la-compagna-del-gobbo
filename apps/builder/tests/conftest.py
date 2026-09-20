"""Helpers that drive the whole creation flow through the services, as the wizard will."""

import pytest
from django.contrib.auth import get_user_model

from apps.builder.services import abilities, class_choices, creation, origins
from apps.builder.services.store import Draft
from apps.builder.tables import STANDARD_ARRAY_BY_CLASS


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user("alice")


def pick_first(picker, taken=()):
    """The first `count` candidates of a picker that aren't in `taken`."""
    ids = [c[0] for c in picker.candidates if c[0] not in taken]
    return ids[: picker.count]


def complete_species(character, species_id):
    """Select a species and answer every sub-choice it asks for, with the first valid answer."""
    assert not origins.select_species(character, species_id)
    draft = Draft(character)
    species = draft.species
    answers = {}
    if len(species.size) > 1:
        answers["size"] = species.size[-1]
    if species.lineages:
        answers["lineage"] = species.lineages[0]["key"]
    origins.save_species_choices(character, **answers)
    draft = Draft(character)
    from apps.builder.resolvers import species as species_resolver
    from apps.builder.resolvers.spell import class_spell_list

    if options := species_resolver.spell_ability_options(draft):
        answers["spell_ability"] = options[0]
    picks = [p for g in species_resolver.spell_grants(draft) for p in g.picks]
    if picks:
        answers["cantrip"] = [
            s.id for p in picks for s in class_spell_list(p.class_name, p.level)[: p.count]
        ]
    for choice in species.choice_definitions.filter(kind__in=["skills", "feats"]):
        if choice.kind == "skills":
            from apps.builder.resolvers import held
            from apps.rules.models import Skill

            blocked = held.held(draft, exclude=("species",))["skills"]
            pool = choice.options or [s.id for s in Skill.objects.order_by("id")]
            answers["skill"] = next(s for s in pool if s not in blocked)
        else:
            answers["feat"] = {"feat": "alert"}
    problems = origins.save_species_choices(character, **answers)
    assert not problems, problems


def complete_background_choices(character):
    draft = Draft(character)
    from apps.builder.resolvers import feat as feat_resolver
    from apps.builder.resolvers import held
    from apps.builder.resolvers.proficiency import background_tool_grant, tool_options
    from apps.builder.resolvers.spell import class_spell_list

    tool = ""
    _fixed, pick = background_tool_grant(draft.background)
    if pick:
        blocked = held.held(draft, exclude=("background",))["tools"]
        tool = next(e.id for e in tool_options(pick[0]) if e.id not in blocked)
    feat_choices = {}
    feat = draft.background.feat
    for p in feat_resolver.picks(feat, draft.background.feat_variant):
        if p.kind == "ability":
            feat_choices[p.key] = p.options[0]
        elif p.kind == "spell":
            spells = [s.id for s in class_spell_list(p.class_name, p.level)[: p.count]]
            feat_choices[p.key] = spells if p.key == "cantrips" else spells[0]
        elif p.kind == "tool":
            blocked = held.held(draft, exclude=("background.feat",))["tools"]
            pool = p.options or [e.id for e in tool_options(p.tool_kinds)]
            feat_choices[p.key] = [t for t in pool if t not in blocked][: p.count]
        elif p.kind == "skill_or_tool":
            blocked = held.held(draft, exclude=("background.feat",))["skills"]
            from apps.rules.models import Skill

            feat_choices[p.key] = [
                f"skill:{s.id}" for s in Skill.objects.order_by("id") if s.id not in blocked
            ][: p.count]
    problems = origins.save_background_choices(character, tool=tool, feat=feat_choices)
    assert not problems, problems


def build_character(owner, class_id, background_id="soldier", species_id="human", name="Test"):
    """Drive every step to completion with the first valid answer at each. Returns the draft."""
    character = creation.start_draft(owner, name)
    assert not origins.select_class(character, class_id)
    assert not origins.select_background(character, background_id)
    complete_background_choices(character)
    complete_species(character, species_id)
    assert not origins.save_languages(character, ["dwarvish", "elvish"])

    from apps.builder.resolvers import equipment as equipment_resolver

    draft = Draft(character)
    groups = {}
    for source in equipment_resolver.SOURCES:
        rows = equipment_resolver.option_rows(equipment_resolver.source_object(draft, source))["A"]
        for row in rows:
            if row.group_id:
                groups[equipment_resolver.group_key(source, row.group_id)] = (
                    row.group.items.first().id
                )
    problems = origins.save_equipment(
        character, class_option="A", background_option="A", groups=groups
    )
    assert not problems, problems

    assigned = STANDARD_ARRAY_BY_CLASS[class_id]
    allowed, spreads = abilities.bonus_rules(Draft(character))
    bonus = dict(zip(allowed, (2, 1), strict=False))
    problems = abilities.save(character, method="standard", base=assigned, bonus=bonus)
    assert not problems, problems

    # Class choices: first valid answer for each picker, in order (later pickers depend on earlier).
    for _round in range(3):
        for picker in class_choices.pickers(Draft(character)):
            chosen = pick_first(picker)
            value = chosen[0] if picker.single else chosen
            class_choices.save(character, **{picker.key.removeprefix("class."): value})
    assert not class_choices.issues(Draft(character)), class_choices.issues(Draft(character))

    assert not origins.save_alignment(character, "NG")
    character.refresh_from_db()
    return character
