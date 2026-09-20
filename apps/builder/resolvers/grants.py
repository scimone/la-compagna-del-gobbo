"""`Grants`: everything a draft's choices hand to the character, before any row is written.

The class/species/background/feat resolvers each add to one `Grants`; `effects.apply()` then
writes it. Keeping "what is granted" (pure, testable, no writes) apart from "write the rows" is
what makes recomputing after every wizard step safe.
"""

from dataclasses import dataclass, field

from apps.rules.models import Feat, Feature, OptionalFeature

_LEVEL_RANK = {"proficient": 1, "expertise": 2}


@dataclass
class SpellRow:
    spell_id: str
    source: str
    klass_id: str | None = None
    prepared: bool = True
    always_prepared: bool = False
    in_spellbook: bool = False


@dataclass
class Grants:
    #: `(category, name) -> "proficient" | "expertise"`. Names are language-neutral ids: skill id,
    #: ability id (saving throws), armor/weapon category, equipment id (tools).
    proficiencies: dict[tuple[str, str], str] = field(default_factory=dict)
    features: list[Feature] = field(default_factory=list)
    feats: list[tuple[Feat, str]] = field(default_factory=list)  # (feat, source)
    optional_features: list[OptionalFeature] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    senses: list[tuple[str, int, str]] = field(default_factory=list)  # (sense id, feet, source)
    spells: dict[str, SpellRow] = field(default_factory=dict)
    resources: list[tuple[str, int, str]] = field(default_factory=list)  # (name, max, reset_on)

    def add_proficiency(self, category: str, name: str, level: str = "proficient") -> None:
        key = (category, name)
        if _LEVEL_RANK[level] > _LEVEL_RANK.get(self.proficiencies.get(key, ""), 0):
            self.proficiencies[key] = level

    def add_language(self, language_id: str) -> None:
        if language_id and language_id not in self.languages:
            self.languages.append(language_id)

    def add_spell(self, row: SpellRow) -> None:
        """A spell reachable through two sources keeps the stronger flags of both."""
        existing = self.spells.get(row.spell_id)
        if existing:
            existing.prepared |= row.prepared
            existing.always_prepared |= row.always_prepared
            existing.in_spellbook |= row.in_spellbook
            existing.klass_id = existing.klass_id or row.klass_id
        else:
            self.spells[row.spell_id] = row
