"""The Druid's Wild Shape: the Beast forms the character has learned.

The SRD's Wild Shape feature (Known Forms, Beast Shapes table): the Druid knows 4 Beast forms at
level 2, 6 at level 4 and 8 at level 8, chosen from the Beast stat blocks (`rules.Creature`) with a
maximum Challenge Rating of 1/4, 1/2 and 1, no Fly Speed until level 8, and no Swarms. After every
Long Rest one known form may be replaced by another eligible one.

The known forms are the list of creature ids in the `wild_shape.forms` `CharacterChoice`. They are
picked when the level is gained (`progression`'s "Wild Shape forms" section, `add_forms()`), or -
for a Druid who got the level before forms were tracked - from the Features tab
(`needed()` says how many are still to choose). A Long Rest opens `rest_choices["wild_shape"]`
(`play.grant_rest_choices()`); `swap_form()` makes the one replacement and closes it.

Using Wild Shape (`use()`, a Bonus Action) spends one use of the "Wild Shape" resource, gives
temporary hit points equal to the Druid level and puts the Beast's statistics on the sheet
(`Character.wild_shape_form`, applied by `derived_stats.compute()`): its Armor Class, Speed,
Strength, Dexterity and Constitution, and any skill bonus higher than the Druid's own, while
Hit Points, Hit Dice, Intelligence, Wisdom, Charisma, proficiencies and class features stay. No
spells can be cast.
The form ends by `end()` (a Bonus Action), by using Wild Shape again (another form), at 0 hit
points or with the Incapacitated condition (`play`), and at a Long Rest. The duration (half the
Druid level in hours) is game time and is only shown, not counted.
"""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.characters.models import Character, CharacterChoice
from apps.rules.models import Creature

KEY = "wild_shape.forms"
REST_KEY = "wild_shape"

#: The Beast Shapes table, highest level first: `(Druid level, known forms, max CR, Fly Speed ok)`.
BEAST_SHAPES = ((8, 8, 1.0, True), (4, 6, 0.5, False), (2, 4, 0.25, False))


def druid_level(character: Character) -> int:
    row = character.classes.filter(klass_id="druid").first()
    return row.level if row else 0


def shapes_at(level: int) -> tuple[int, float, bool] | None:
    """`(known forms, max CR, Fly Speed ok)` at this Druid level; None below level 2."""
    for at, forms, cr, fly in BEAST_SHAPES:
        if level >= at:
            return forms, cr, fly
    return None


def known_ids(character: Character) -> list[str]:
    row = CharacterChoice.objects.filter(character=character, key=KEY).first()
    return list(row.value) if row else []


def known_forms(character: Character) -> list[Creature]:
    by_id = Creature.objects.in_bulk(known_ids(character))
    return sorted((by_id[i] for i in known_ids(character) if i in by_id), key=lambda c: c.name)


def eligible(level: int, exclude=()) -> list[Creature]:
    """The Beasts a Druid of this level may learn (not the ones in `exclude`), by name."""
    shapes = shapes_at(level)
    if shapes is None:
        return []
    _forms, max_cr, fly = shapes
    return [
        c
        for c in Creature.objects.filter(type__iexact="Beast", cr_value__lte=max_cr).order_by(
            "name"
        )
        if c.pk not in exclude and (fly or not c.has_fly_speed) and "swarm" not in c.name.lower()
    ]


def needed(character: Character, level: int | None = None) -> int:
    """How many forms the Druid may still learn: what the table allows (at `level`, default the
    Druid's own) less what is known."""
    shapes = shapes_at(druid_level(character) if level is None else level)
    return max(0, shapes[0] - len(known_ids(character))) if shapes else 0


@transaction.atomic
def add_forms(character: Character, ids, level: int | None = None) -> None:
    """Learn these forms (at most `needed()`, each eligible and new)."""
    ids = list(dict.fromkeys(ids))
    level = druid_level(character) if level is None else level
    have = known_ids(character)
    if len(ids) > needed(character, level):
        raise ValueError("too many Wild Shape forms")
    allowed = {c.pk for c in eligible(level, exclude=have)}
    if not ids or any(i not in allowed for i in ids):
        raise ValueError("not an eligible Wild Shape form")
    CharacterChoice.objects.update_or_create(
        character=character, key=KEY, defaults={"value": have + ids}
    )


def swap_options(character: Character) -> dict | None:
    """`{"known": [Creature], "candidates": [Creature]}` while a Long Rest's replacement is open."""
    if not character.rest_choices.get(REST_KEY):
        return None
    known = known_forms(character)
    return {
        "known": known,
        "candidates": eligible(druid_level(character), exclude={c.pk for c in known}),
    }


@transaction.atomic
def swap_form(character: Character, out_id: str, in_id: str) -> None:
    """Replace one known form with another eligible one, and close the Long Rest's choice."""
    options = swap_options(character)
    if options is None:
        raise ValueError(_("There is no Wild Shape form to replace now."))
    if out_id not in {c.pk for c in options["known"]}:
        raise ValueError("that form is not known")
    if in_id not in {c.pk for c in options["candidates"]}:
        raise ValueError("not an eligible Wild Shape form")
    ids = [in_id if i == out_id else i for i in known_ids(character)]
    CharacterChoice.objects.update_or_create(character=character, key=KEY, defaults={"value": ids})
    close_rest_choice(character)


def close_rest_choice(character: Character) -> None:
    rest_choices = dict(character.rest_choices)
    rest_choices.pop(REST_KEY, None)
    character.rest_choices = rest_choices
    character.save(update_fields=["rest_choices"])


RESOURCE = "Wild Shape"


def active_form(character: Character) -> Creature | None:
    """The Beast the character is shape-shifted into right now, if any."""
    if not character.wild_shape_form:
        return None
    return Creature.objects.filter(pk=character.wild_shape_form).first()


def uses_left(character: Character) -> int:
    row = character.resources.filter(name=RESOURCE).first()
    return row.current_uses if row else 0


def duration_hours(character: Character) -> float:
    """How long the form lasts: half the Druid level, in hours."""
    return druid_level(character) / 2


@transaction.atomic
def use(character: Character, creature_id: str) -> None:
    """Shape-shift into a known form: spends a use of Wild Shape (also when already in a form -
    using it again is how the Beast changes), grants the temporary hit points."""
    if creature_id not in known_ids(character):
        raise ValueError("that is not one of your Wild Shape forms")
    # Imported here: `play` calls back into this module's world.
    from apps.characters import conditions

    if conditions.effects(character).incapacitated or character.current_hit_points < 1:
        raise ValueError(_("You cannot use Wild Shape while Incapacitated."))
    row = character.resources.select_for_update().filter(name=RESOURCE).first()
    if row is None or row.current_uses < 1:
        raise ValueError(_("No Wild Shape uses left."))
    row.current_uses -= 1
    row.save(update_fields=["current_uses"])
    character.wild_shape_form = creature_id
    character.temporary_hit_points = max(character.temporary_hit_points, druid_level(character))
    character.save(update_fields=["wild_shape_form", "temporary_hit_points", "updated_at"])


def end(character: Character) -> None:
    """Leave the form (a Bonus Action). The temporary hit points stay until lost."""
    if character.wild_shape_form:
        character.wild_shape_form = ""
        character.save(update_fields=["wild_shape_form", "updated_at"])
