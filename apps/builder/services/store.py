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
    details {backstory{...}, trinket}                        manual.abilities {ab: score}
    manual.skills {skill id: "none"|"proficient"|"expertise"}
"""

from dataclasses import dataclass

from apps.characters.models import Character, CharacterChoice, CharacterClass

STEPS = (
    "class",
    "background",
    "species",
    "languages",
    "equipment",
    "abilities",
    "choices",
    "alignment",
    "details",
    "review",
)


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
