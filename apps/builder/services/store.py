"""The wizard's state: what has been decided so far about one draft `Character`.

The player's picks live in `characters.CharacterChoice` (JSON, keyed by a dotted string), plus the
few first-class fields (`Character.species/background/alignment`, the starting `CharacterClass`).
Everything else - proficiencies, features, spells, inventory, ability scores - is *derived* from
those picks by `effects.apply()`, never edited directly. That is what lets the player go back and
change the background without leaving stale grants behind.

Choice keys (value shapes) used across the builder:

    class.skills [skill id]          class.tools [equipment id]      class.weapon_mastery [id]
    class.fighting_style feat id     class.order option slug         class.expertise [skill id]
    class.cantrips / class.spellbook / class.spells [spell id]       class.invocations [id]
    class.language language id       background.tool equipment id
    background.feat / species.feat   {variant?, feat?, <pick key>: value}   (see resolvers.feat)
    species.size "S"|"M"             species.lineage lineage key    species.skill skill id
    species.spell_ability ability    species.cantrip spell id
    languages [language id]          equipment.class / equipment.background "A"|"B"|"C"
    equipment.groups {"class:holy-symbol": equipment id, ...}
    abilities {method, base{ab:n}, rolled[n], rolls[[n]], bonus{ab:n}}
    manual.abilities {ab: score}     (the backstory is `Character.backstory`, not a choice)
    manual.skills {skill id: "none"|"proficient"|"expertise"}
"""

from dataclasses import dataclass, field

from apps.characters.models import Character, CharacterChoice, CharacterClass

#: The class's own level-1 choices (skills, weapon mastery, spells, ...) are part of the "class"
#: step, shown right under the picked class - not a separate step later on.
STEPS = (
    "background",
    "class",
    "species",
    "languages",
    "equipment",
    "abilities",
    "alignment",
    "story",
    "review",
)


#: Set while an admin has reopened a finished character in the wizard (`creation.reopen()`).
EDITING_KEY = "meta.editing"


@dataclass(frozen=True)
class Issue:
    """One thing wrong or missing, structured so a screen can place it (README: "the frontend
    never has to duplicate rules knowledge")."""

    step: str
    code: str
    message: str
    path: str = ""

    def as_dict(self) -> dict:
        return {"step": self.step, "code": self.code, "message": self.message, "path": self.path}


class Draft:
    """A character and every decision made about it so far, loaded once per request."""

    def __init__(self, character: Character):
        self.character = character
        self.choices: dict = {
            c.key: c.value for c in CharacterChoice.objects.filter(character=character)
        }
        self.class_row = (
            CharacterClass.objects.filter(character=character, is_starting_class=True)
            .select_related("klass")
            .first()
        )
        self.klass = self.class_row.klass if self.class_row else None
        self.background = character.background
        self.species = character.species

    def get(self, key: str, default=None):
        return self.choices.get(key, default)

    @property
    def level(self) -> int:
        return self.class_row.level if self.class_row else 1


def set_choice(character: Character, key: str, value) -> None:
    CharacterChoice.objects.update_or_create(
        character=character, key=key, defaults={"value": value}
    )


def clear_choices(character: Character, *prefixes: str) -> None:
    """Forget every choice whose key starts with one of `prefixes` (e.g. `"class."`)."""
    for prefix in prefixes:
        CharacterChoice.objects.filter(character=character, key__startswith=prefix).delete()


@dataclass
class Picker:
    """One thing the player must choose: how many, from which candidates, what is selected now.

    The wizard screens render pickers and validation judges them, so what a form offers and what
    validation accepts are the same list. `key` is the dotted choice key (`"class.skills"`); a key
    under `species.feat.` / `background.feat.` lives inside that feat's dict (`NESTED`).
    """

    key: str
    label: str
    count: int
    candidates: list[tuple[str, str]]  # (id, display name)
    selected: list[str] = field(default_factory=list)
    single: bool = False  # stored as a bare value instead of a list
    #: What the candidates are, so a screen can render them as catalog cards (icon, properties,
    #: readable description) instead of a bare list: `plain` | `spell` | `equipment` | `feat` |
    #: `invocation` | `skill`.
    kind: str = "plain"
    #: A change here changes what *other* pickers offer (a lineage changes the cantrip list, a
    #: skill changes who can take Expertise), so the screen re-reads the step when it changes.
    refresh: bool = False
    hint: str = ""
    #: An optional pick (a swap on level-up): leaving it empty is fine, choosing is allowed.
    optional: bool = False

    @property
    def candidate_ids(self) -> set[str]:
        return {c[0] for c in self.candidates}


#: Choice keys whose value is a dict of that feat's own picks.
NESTED = ("species.feat", "background.feat")


def split_key(key: str) -> tuple[str, str | None]:
    """`"species.feat.cantrips"` -> `("species.feat", "cantrips")`; a plain key -> `(key, None)`."""
    for prefix in NESTED:
        if key.startswith(prefix + "."):
            return prefix, key[len(prefix) + 1 :]
    return key, None


def stored(draft: Draft, key: str, single: bool) -> list[str]:
    """The current selection for a picker key, as a list."""
    choice_key, sub = split_key(key)
    value = draft.get(choice_key)
    if sub is not None:
        value = (value or {}).get(sub)
    if single:
        return [value] if value else []
    return list(value or [])


def picker_issues(step: str, pickers: list[Picker]) -> list[Issue]:
    from django.utils.translation import gettext as _

    found: list[Issue] = []
    for picker in pickers:
        chosen = picker.selected
        if picker.optional and not chosen:
            continue
        if len(chosen) != picker.count or len(set(chosen)) != len(chosen):
            code = "wrong_count"
            message = _("%(label)s: choose %(count)d.") % {
                "label": picker.label,
                "count": picker.count,
            }
        elif not set(chosen) <= picker.candidate_ids:
            code = "invalid_choice"
            message = _("%(label)s: one of your choices isn't available.") % {"label": picker.label}
        else:
            continue
        found.append(Issue(step, code, message, picker.key))
    return found


def read_values(pickers: list[Picker], getlist) -> dict:
    """Collect submitted values for `pickers` (`getlist(name)` like `QueryDict.getlist`), returning
    `{choice_key: value}` with each feat's picks folded into that feat's dict."""
    values: dict = {}
    for picker in pickers:
        submitted = [v for v in getlist(picker.key) if v]
        value = (submitted[0] if submitted else "") if picker.single else submitted
        choice_key, sub = split_key(picker.key)
        if sub is None:
            values[choice_key] = value
        else:
            values.setdefault(choice_key, {})[sub] = value
    return values


def store_picker(character: Character, key: str, value) -> None:
    """Write one picker's value, folding a feat's own picks into that feat's dict."""
    choice_key, sub = split_key(key)
    if sub is None:
        set_choice(character, choice_key, value)
        return
    row = CharacterChoice.objects.filter(character=character, key=choice_key).first()
    current = dict(row.value or {}) if row else {}
    current[sub] = value
    set_choice(character, choice_key, current)
