# Character creation — implementation plan

Status: **implementation in progress** — see the progress table right below. Written 2026-09-20 from a read of the SRD chapter
"Creazione del personaggio" (`IT_SRD_CC_v5.2.1.md`, lines 1169–1866: creation steps, level
advancement, starting at higher levels, multiclassing, trinkets) and an audit of the `rules` and
`characters` models **against the live database** (12 classes, 240 class levels, 16 backgrounds,
11 species, 77 feats, 391 spells, 217 equipment rows, 0 characters).

Everything marked **[verified]** was checked by querying the DB or `db/*.json`, not inferred from
docstrings. Everything marked **[assumption]** was not.

## Progress log

Updated after every completed phase (and committed with it). Legend: ✅ done · 🔧 in progress · ⬜ not started.

| Phase | Status | Commit / notes |
|---|---|---|
| 0 — Data fixes | ✅ | Importer fixes for §3.2 #1–#4 (class weapons, background skills, species lineages/resistances/spells, feat spells/grants, background `feat_variant`); migration `rules.0018`; 9 integrity tests in `apps/rules/tests/test_builder_data.py`; live DB re-imported. Skill-choice `options` are now real `Skill` ids. §3.2 #5 (`"artificer"` code) is left for Phase 8 as planned |
| 1 — Schema | ✅ | Migration `characters.0002`: `Character.owner/status/experience_points`, `CharacterClass.is_starting_class/hit_dice_spent`, `CharacterSpell.klass/in_spellbook`, **`CharacterInventoryItem.parent`** (pack traceability, D3). `status` defaults to `complete` so API-created characters stay ordinary; the wizard sets `draft`. `admin.py` is still the empty stub it was (nothing to update). 3 tests in `apps/characters/tests/test_builder_fields.py` |
| 2 — Tables + class spec | ✅ | `apps/builder/tables.py` (array, array-by-class, point buy, XP, PB, HP, 1d12 languages, alignments, armor dex caps) and `apps/builder/class_spec.py` (weapon mastery, fighting style, orders, expertise, spellbook, invocations, languages, always-prepared spells, tool picks, L1 resources, unarmored defense). 28 tests incl. cross-checks against the imported DB. **Findings:** (a) Monk's source lists two tool grants but the text says pick *one*; (b) "Staff"/"Wooden Staff" are focus-typed duplicates of the Quarterstaff, so the mastery weapon pool is `type in {m, r}` (39 weapons; Barbarian's "melee" = type `m`); (c) Rage/Second Wind recover one use on a short rest, all on a long one (`reset_on="other"`). **Deferred:** trinket table (100 entries, Italian only — D5) moves to Phase 5 (details screen); `HIGHER_LEVEL_EQUIPMENT` dropped for now (D4, level 1 only) |
| 3 — Builder engine (level 1) | ✅ | Services `store` (Draft/Issue/choice keys), `origins` (class, background, species, languages, equipment, alignment), `abilities`, `class_choices` (a single `pickers()` description feeds both the screen and validation), `effects` (recompute-from-choices), `validation`, `creation` (start/state/details/manual layer/finalize/discard); resolvers `spell`, `proficiency`, `feat`, `equipment`, `held`, `abilities`, `class_`, `species`, `background`, `grants`. **All 12 classes** go through the full flow and finish; 51 tests (`test_creation_flow`, `test_creation_rules`). Design notes: (1) for a *draft*, `effects.apply()` deletes and rebuilds **all** generated rows rather than tagging them with a `source` (several tables have no `source` column); a *complete* character is never recomputed. (2) `CharacterProficiency.name` holds language-neutral ids (skill id, ability id, armor/weapon category, equipment id), the UI translates them. (3) Manual layer: `manual.abilities`/`manual.skills`, applied last, survives recomputes; the ability-sum invariant is kept with a `manual` delta row. (4) Rogue's filtered weapon grant is stored as e.g. `martial:f,l`. (5) The REST stubs in `apps/builder/api/` are **not** wired yet — the frontend calls the services directly, as planned |
| 4 — Derived stats | ⬜ | |
| 5 — List + wizard UI | ⬜ | |
| 6 — Finish + landing page | ⬜ | |
| 6.5 — Optional shop | ⬜ | |
| 7 / 8 / 9 — higher level, multiclass, character page | ⬜ | deliberately later (D4) |

### TODO for the project owner
- **Trinkets (Monili):** the Italian table is in the SRD md; the English text is not in the repo.
  Provide the English text later. Until then the trinket table ships with the Italian text for
  *both* language versions (D5).

## Decisions taken (2026-09-20)

| # | Decision |
|---|---|
| D1 | **Every character is assigned to the account that created it (`owner`), but *all* characters are visible to *all* accounts.** The list shows everyone's characters (with the owner's name). Later the owner may want to hide certain sub-menus of a character from other accounts, so ownership is stored and exposed to the templates now, and visibility is centralised in one function (`can_view(user, character, section)`, returns `True` for now) so that can be added without touching every view. Editing/deleting is limited to the owner |
| D2 | Offer **everything** in the DB (not only `srd=True`) |
| D3 | **Packs: both.** A pack is stored as *individual `Equipment` items* (`EquipmentPackContent`, already so in the DB), and each inventory item created from a pack stays **traceable to its pack**: the pack itself is an inventory row and each content row points at it (`CharacterInventoryItem.parent`). On the character page a pack shows as one line that expands to its contents |
| D4 | **Level 1 only for now.** The structure stays level-agnostic; higher start levels are Phase 7, undecided |
| D5 | Trinkets: leave the Italian text for both languages for now (TODO above) |
| D6 | Adopt: no duplicate proficiencies offered by later pickers; re-roll a duplicate 1d12 language |
| D7 | One stored ability-score roll per character |
| D8 | Magic items for higher levels: not needed |
| **New** | **Ability scores and skills are fully manually adjustable at the end** (Review step), *regardless of what class, species or background say*: any score (1–30, no 20 cap) and any skill's state (none / proficient / expertise). Stored as a final override layer (`CharacterChoice` keys `manual.abilities` / `manual.skills`) applied *after* all generated grants, so recomputing from the wizard's choices never destroys a manual edit |


Contents: 1. Goal · 2. SRD → flow map · 3. Data audit (the answer to "are the models
sufficient?") · 4. Architecture · 5. UX / screens · 6. Per-step rules · 7. Derived stats ·
8. Phases · 9. Tests · 10. Decisions needed · 11. Out of scope

---

## 1. Goal and scope

Under the bottom-nav **Characters** menu (`/characters/`, currently a "Coming soon" placeholder,
`views.characters_overview`):

- a **list** of characters, with a **`+` button** that starts creation;
- a **creation wizard** that walks the SRD's five steps in order, enforcing every rule in the
  chapter, persisting progress so it survives reloads, back-navigation and leaving the app;
- on finish, a saved `Character` with all its rows (class, proficiencies, features, spells,
  inventory, currency, HP, ...).

**In scope:** everything in the chapter — steps 1–5, starting at a level above 1, and the
level-up / multiclass rules (as the same engine, built after the level-1 flow ships; see phases).
**Out of scope (per the request):** the character *sheet* page shown when tapping a character.
A bare read-only summary is still needed as the landing page after "finish" — see Phase 6.

---

## 2. SRD → wizard map

| SRD step | Wizard screen(s) | What the SRD asks for |
|---|---|---|
| Intro | **New character** | Name; **starting level** (default 1; "the GM may start you higher") |
| 1 — Classe | **Class** | Pick one of 12 classes (overview table: primary ability, complexity). Class gives armor/weapon/tool proficiencies, saving throws, hit die |
| 2 — Origini | **Background** | Background → 3 candidate abilities, an origin feat, 2 skills, 1 tool |
| 2 | **Species** | Species → size (if several), speed, traits, darkvision; lineage/ancestry choices |
| 2 | **Languages** | Common + 2 more: chosen from the standard table **or rolled** on 1d12 |
| 2 | **Equipment** | Class option (A/B/C) **and** background option (A/B); may spend the gold immediately |
| 3 — Caratteristiche | **Ability scores** | Method: standard array / 4d6-drop-lowest / 27-point buy → assign to 6 abilities → apply background +2/+1 or +1/+1/+1 (cap 20) → modifiers |
| 4 — Allineamento | **Alignment** | One of 9 (warning, not a block, for evil) |
| 5 — Dettagli | **Class choices** | Level-1 features and their choices (skills, weapon mastery, fighting style, expertise, order, spells/cantrips, invocation) |
| 5 | **Details** | Numbers are computed; the player adds appearance, backstory answers, an optional **trinket** (1d100) |
| — | **Review** | Full computed summary → Finish |

Order note: the SRD puts class *choices* under step 5 (after abilities), because several depend
on ability scores (Bard's Bardic Inspiration uses = Cha mod, spell DCs, HP = die + Con mod). The
wizard follows that order, but lets the player navigate freely back to earlier screens.

---

## 3. Data audit — are the DB models and entries sufficient?

**Short answer: the catalogs are mostly there, the model shapes are mostly right, but not
sufficient as-is.** Four import gaps must be fixed first (some silently lose data today), about
ten static tables from the chapter don't exist anywhere in `db/`, level-1 class choices live only
in prose, and `characters` needs a handful of fields to represent an in-progress character.

### 3.1 Sufficient as-is [verified]

| Need | Where it lives |
|---|---|
| The 12 classes, hit die, primary abilities (+ and/or), saving throws, armor proficiencies, spellcasting ability | `Class` |
| Skill picks per class (count + allowed list; Bard "any 3") | `ChoiceDefinition(kind="skills")` — all 12 classes present |
| Per-level spell slots, cantrips known, prepared/known count | `ClassLevel.spell_slots / cantrips_known / spells_known_or_prepared` (Warlock's pact slots in `columns["Spell Slots"/"Slot Level"]`) |
| Class resource counts (Rages, Second Wind, Favored Enemy, ...) | `ClassLevel.columns` |
| Level-1 features per class | `Feature` rows via `class_level`; Cleric *Divine Order* and Druid *Primal Order* are real `{"type":"options"}` nodes with `refClassFeature` children |
| Subclass at level 3 for all 12 classes (4 each) + subclass features | `Subclass` / `SubclassLevel` / `Feature` |
| ASI levels (4/8/12/16; Fighter +6/14; Rogue +10) | `Feature` named "Ability Score Improvement" |
| Background: 3-ability weighted spread (+2/+1 **or** +1/+1/+1), skills, tool, origin feat | `Background.ability_scores / skills / tools / feat` |
| Background & class starting-equipment options (A/B, Fighter A/B/C), incl. gold | `*StartingEquipmentOption` (`gold_value` is in **copper**: Fighter A = 400 = 4 GP) |
| "Any holy symbol" style picks | `EquipmentGroup` (+ `focus_classes`) |
| Named tool grants resolve to items (all 13 checked, e.g. `calligraphers-supplies`) | `Equipment.name.lower()` match |
| "Any artisan tool / instrument / gaming set" picks | resolve by `EquipmentType` (`at` 17, `ins` 10, `gs` 4) — **not** by `EquipmentGroup.items`, whose artisan/instrument/gaming groups are empty |
| All 19 languages, standard vs rare split matching the SRD tables | `Language.language_type` |
| Weapons: category, damage, properties, **mastery** (41 weapons have one), cost, weight | `Equipment` (+ `weapon_category`, `masteries`) |
| Armor: AC, Str requirement, stealth disadvantage; type `la/ma/ha/s` | `Equipment.ac / strength_requirement / stealth_disadvantage / type` — consistent with the SRD "Armature" table (`IT_SRD_CC_v5.2.1.md` ~line 6855; e.g. chain mail AC 16, Str 13, stealth disadvantage) |
| Spell lists per class (cantrips, level 1) | `Spell.classes` (JSON of class names) — all 8 casting classes have cantrips/level-1 spells; Paladin/Ranger correctly have 0 cantrips |
| Fighting-style feats | `Feat.category` = "Fighting Style" / "(P)" / "(R)"; Origin feats = "Origin" (10) |
| Optional class picks (invocations 28, maneuvers 20, metamagic 10) with structured prerequisites | `OptionalFeature` |
| Spell slots for multiclass casters | The SRD "Multiclass Spellcaster" table is identical to a *full caster's* slot row for that level, so it is derivable from `ClassLevel(wizard, N).spell_slots` — no new table |
| Proficiency bonus | Formula `2 + (level-1)//4` reproduces every row of the SRD table; not stored in `ClassLevel.columns` |
| Level-up HP (fixed value) | `hit_die//2 + 1` reproduces the SRD "fixed HP" table (12→7, 10→6, 8→5, 6→4). Level-1 HP = full die + Con mod |
| Ability modifier | `(score - 10) // 2` reproduces the SRD table incl. 3→−4, 9→−1, 20→+5 |
| Persisted result | `Character`, `CharacterClass`, `CharacterProficiency`, `CharacterFeature`, `CharacterFeat`, `CharacterOptionalFeature`, `CharacterLanguage`, `CharacterSense`, `CharacterSpell`, `CharacterInventoryItem`, `CharacterCurrency`, `CharacterResource`, `CharacterAbilityScoreIncrease`, `CharacterChoice` — all already exist |

### 3.2 Import bugs / gaps to fix first (they corrupt or omit data creation depends on)

These are all in `apps/rules/management/commands/import_rules_data.py`. **They must be fixed
before the first real `Character` exists** — after that, re-running `import_rules_data` raises
`ProtectedError` (every `characters` → `rules` FK is `PROTECT`).

1. **Class weapon proficiencies are empty for 10 of 12 classes.** [verified] The source gives
   `startingProficiencies.weapons: ["simple", "martial"]` for every class, but the importer reads
   only `weaponProficiencies`, which exists solely for Monk and Rogue. So Barbarian, Fighter,
   Paladin, Ranger (Simple+Martial) and Bard, Cleric, Druid, Sorcerer, Warlock, Wizard (Simple)
   have `weapon_proficiencies == []`. Fix: fall back to the `weapons` list (`["simple","martial"]`
   → `[{"simple": True, "martial": True}]`). Also affects the `Proficiency` catalog (47 rows) and
   the World class page's "Weapons" fact.
2. **Background skills silently dropped for multi-word skills.** [verified] `skill_by_id[i] for i
   in skill_ids if i in skill_by_id` compares the source's spaced key (`"sleight of hand"`,
   `"animal handling"`) to slug ids (`sleight-of-hand`, `animal-handling`) and discards the
   misses. Charlatan, Criminal, Farmer, Merchant each have **1 skill instead of 2** in the DB.
   Fix: slugify keys. Add a test: *every* background has exactly 2 skills. Related trap:
   `ChoiceDefinition.options` for class skills also store the spaced names — consumers must
   slugify (or the importer should normalize them; preferred, so options are real `Skill` ids).
3. **Species lineages/ancestries and species-granted spells/resistances/skills are not imported.**
   [verified] `_versions` (Elf: Drow/High/Wood; Gnome: Forest/Rock; Goliath: 6 giant ancestries;
   Tiefling: Abyssal/Chthonic/Infernal; Dragonborn: 10 colors), `additionalSpells` (Aasimar's
   *Light*, all lineage cantrips/spells and their "choose Int/Wis/Cha" casting ability), flat
   `resist` (Aasimar), flat `skillProficiencies` are in `db/species.json` but only reach the DB as
   prose inside `Species.entries`/`Feature` rows. Only `Subclass.additionalSpells` is imported
   today. A wizard cannot offer "Elven Lineage: Drow/High Elf/Wood Elf" or grant the right
   cantrip/speed/darkvision without this. Fix: add structured fields (see 3.5) and import them.
4. **Feat variants and feat grants are dropped.** [verified] Acolyte/Guide/Sage grant *Magic
   Initiate (Cleric / Druid / Wizard)* — the source key is `magic initiate; cleric|xphb`, and
   `_feat_ref_base_name` strips the `; cleric` suffix, so all three just say `magic-initiate`.
   The feat's own structured data (`additionalSpells`: "2 cantrips + one level-1 spell from list
   X, ability = Int/Wis/Cha") and `skillToolLanguageProficiencies` (Skilled: "any 3 skills/tools")
   are in `db/feats.json` but not imported; `ChoiceDefinition` has **no rows** for any Origin feat.
   Fix: keep the variant on `Background` (e.g. `feat_variant="cleric"`) and add
   `Feat.additional_spells` / `Feat.grants` JSON, same treatment as `Subclass.additional_spells`.
5. Minor: `Class.caster_progression` is `"artificer"` for Paladin/Ranger (5etools' code for
   "half caster, round **up**", which is exactly the SRD multiclass rule) — correct but opaque;
   normalize to a documented value when the multiclass work starts (Phase 8).
6. Minor: importing more fields means `db/it/*.json` needs no change (the new fields are
   structured data, not translatable prose), but the lineage *names* shown in the UI do
   (see §5, i18n).

### 3.3 Static tables from the chapter that exist nowhere in `db/`

`db/handbook.json` holds only chapter 1 ("Playing the Game"). [verified] None of the following
is in any `db/` file; each becomes a code constant in a new module `apps/builder/tables.py`
(tested pure-Python; **not** rules-table rows, because `import_rules_data` wipes the `rules`
tables and there is no source JSON to reload them from):

| Constant | SRD source | Notes |
|---|---|---|
| `STANDARD_ARRAY = (15,14,13,12,10,8)` | Step 3 | |
| `STANDARD_ARRAY_BY_CLASS` (12 × 6) | "Serie standard per classe" | Test: each class's top scores land on its `primary_abilities` |
| `POINT_BUY_COST` `{8:0 … 15:9}`, budget 27 | "Costi in punti" | Range 8–15 before bonuses |
| `ALIGNMENTS` (9, codes `LG NG CG LN N CN LE NE CE`) | Step 4 | Names/blurbs need EN + IT (gettext) |
| `STANDARD_LANGUAGES_D12` (1→sign … 12→orc) | "Lingue standard" | Maps to `Language` ids; Common is automatic |
| `XP_BY_LEVEL` (20 rows) | "Avanzamento dei personaggi" | Starting XP = threshold of the start level; the chapter's own example: level 10 → 64,000 |
| `HIGHER_LEVEL_EQUIPMENT` | "Equipaggiamento di partenza a livelli superiori" | 2–4: standard; 5–10: +500 gp +1d10×25 gp; 11–16: +5,000 gp +1d10×250 gp; 17–20: +20,000 gp +1d10×250 gp. Magic-item counts are informational — see §10 |
| `TRINKETS` (100) | "Monili" | Italian text exists in the SRD md; **the English text is not in the repo** (§10) |
| `ARMOR_DEX_CAP` by type (`la` none, `ma` 2, `ha` 0) | SRD armor table [verified above] | Chain shirt 13+Dex(max 2), chain mail 16 flat, shield +2 |

### 3.4 Level-1 class choices exist only as prose → `CLASS_CREATION_SPEC`

[verified] Beyond the two structured `options` nodes (Divine Order, Primal Order), the rules that
say *how many* of *what* to pick are English/Italian sentences in `Feature.entries`. There are
only 12 classes, so encode them once, by hand, in `apps/builder/class_spec.py`, and add a test that
fails if a class row's feature names drift from the spec:

| Class | Level-1 choices beyond skills |
|---|---|
| Barbarian | Weapon Mastery: 2 kinds of Simple/Martial **Melee** weapons (count also in `columns["Weapon Mastery"]`) |
| Bard | 2 cantrips + 4 prepared spells (from `ClassLevel`); 3 instruments (tool choice) |
| Cleric | Divine Order (Protector / Thaumaturge — the *choice* is structured, its *effects* are prose): **Protector = Martial weapons + Heavy armor proficiency**; **Thaumaturge = +1 Cleric cantrip and an Int (Arcana/Religion) bonus equal to Wis mod, min +1**. 3 cantrips + 4 prepared |
| Druid | Primal Order (structured choice, prose effects): **Warden = Martial weapons + Medium armor proficiency**; **Magician = +1 Druid cantrip and an Int (Arcana/Nature) bonus equal to Wis mod, min +1**. Druidic language + *Speak with Animals* always prepared; 2 cantrips + 4 prepared |
| Fighter | Fighting Style feat (`category="Fighting Style"`); Weapon Mastery ×3 (Simple/Martial) |
| Monk | Weapons: Simple + Martial-with-Light; 1 artisan tool **or** instrument; Unarmored Defense |
| Paladin | Weapon Mastery ×2 (weapons you have proficiency with); 2 prepared spells |
| Ranger | Weapon Mastery ×2; 2 prepared spells; *Hunter's Mark* always prepared (+ Favored Enemy uses from `columns`) |
| Rogue | Expertise ×2 (in skills you're proficient in); Weapon Mastery ×2; Thieves' Cant **+ one more language** of choice |
| Sorcerer | 4 cantrips + 2 prepared; Innate Sorcery (2 uses) |
| Warlock | 1 Eldritch Invocation (respecting prerequisites, e.g. level-gated ones excluded); 2 cantrips + 2 prepared; Pact Magic slots from `columns` |
| Wizard | 3 cantrips; **spellbook of 6** level-1 spells (count only in prose) from which 4 are prepared; Ritual Adept; Arcane Recovery |

The same applies to **Origin feats with sub-choices** (no `ChoiceDefinition` rows exist for any):
Magic Initiate (list per background; 2 cantrips + 1 level-1 spell; Int/Wis/Cha), Skilled (any 3
skills/tools), Musician (3 instruments), Crafter (3 artisan tools). Once 3.2 #4 is fixed these
come from `Feat.additional_spells` / `Feat.grants`; until then they'd be hand-coded.

### 3.5 Schema changes needed in `characters` (and small ones in `rules`)

The `Character` docstring already anticipates a mid-creation row ("species/background nullable
because the builder creates a Character up front"). What's missing:

| Change | Why |
|---|---|
| `Character.status` (`draft` / `complete`) | Distinguish resumable drafts from finished characters; list shows both |
| `Character.owner` → `settings.AUTH_USER_MODEL`, **nullable** | The Characters menu must list *your* characters (§10-D1). Nullable keeps the existing `/api/characters` behaviour |
| `Character.experience_points` | The chapter tracks XP; a level-N start begins at the level's threshold. Not stored anywhere today |
| `CharacterClass.is_starting_class` | Level-1 HP and starting proficiencies apply only to the *first* class (multiclass rules); needed for Phase 8 but trivial to add now |
| `CharacterClass.hit_dice_spent` | SRD sheet tracks spent Hit Dice per die type |
| `CharacterSpell.klass` (nullable FK `rules.Class`) and `in_spellbook` | SRD multiclass: "each prepared spell is associated with one of your classes" (its casting ability). Wizard's spellbook (6) is a superset of its prepared spells (4) |
| `Background.feat_variant`, `Feat.additional_spells`, `Feat.grants`, `Species.additional_spells`, `Species.lineages` (JSON, from `_versions`), `Species.resistances`, `Species.skill_grants` | Import fixes in §3.2 #3–#4 |

Everything else fits `CharacterChoice` (JSON keyed by string, exactly what its docstring says it's
for): weapon-mastery picks, species lineage/size, spell-casting-ability choice for species spells,
the rolled ability values, the chosen 1d12 languages, personality answers, trinket, the current
wizard step. **No new tables are proposed.**

---

## 4. Architecture

Follow the existing layering (`rules` → `characters` → `builder`, `frontend` on top) and the
README's conventions (models one-per-file, no logic in routers/views, logic in `services/`).

```
apps/builder/
  tables.py            # §3.3 constants (pure data, no imports from Django models)
  class_spec.py        # §3.4 per-class level-1 choice spec
  services/
    creation.py        # state machine: start_draft, get_state, step statuses, finalize
    choices.py         # resolve/validate one choice (options offered + validation)
    validation.py      # whole-character check -> [{path, code, message}] (structured, per README)
    effects.py         # apply grants -> characters rows (idempotent: "recompute from choices")
    derived_stats.py   # §7 — AC, saves, skills, passive Perception, DC, ... (never persisted)
    progression.py     # Phase 7-8: level-up / multiclass
  resolvers/           # class_, species, background, feat, equipment, spell, proficiency
apps/frontend/         # views + templates for the wizard; call builder services directly
```

Key design decisions:

- **Choices are the source of truth; grants are derived.** The wizard writes the player's picks
  to `CharacterChoice` (+ `Character.species/background`, `CharacterClass`); `effects.apply()`
  *deletes and recreates* every generated row (proficiencies, features, feats, spells, inventory,
  languages, senses, resources, ability increases) from those choices. That makes "go back and
  change the background" trivial and correct — no reverse-engineering of stale grants. Rows carry
  a `source` string (`"class:fighter"`, `"background"`, `"species"`) so the recompute touches only
  creation-generated rows.
- **Draft persistence = a real `Character` row** with `status="draft"` (as the model docstring
  intended), not the session. Survives reload/PWA restarts, appears in the list, resumable.
  HP and derived numbers are computed at the Review step / finalize, not incrementally.
- **REST API:** the stubs in `apps/builder/api/` (`/builder/class`, `/background`, `/species`,
  `/ability-scores`, `/starting-equipment`, `/choices/{key}`, `/finalize`, `/validation`) map 1:1
  to these services. Build services first; wire the endpoints after the UI works (thin — each is
  one service call). The frontend does **not** go through HTTP (like the existing World views).
- **Server-side randomness:** 4d6 rolls, the 1d12 language rolls and the trinket roll happen on the
  server (`secrets`) and are stored in `CharacterChoice`, so a refresh/back doesn't re-roll.
- **Validation is structured** (`path`/`code`/`message`) so screens show errors inline and the
  Review step can list what's missing — the frontend never re-implements a rule.

---

## 5. UX / screens

- **`/characters/`** — list of the signed-in user's characters (drafts marked "In creation —
  resume", finished ones with name / species / class+level). Empty state invites creating one.
  The **`+`** is a floating action button bottom-right above the bottom nav, on this root page
  only (the header is already busy with back / title / language / account). Signed out → the
  button and empty state route to the account page with `?next=` (accounts are password-less;
  see §10-D1).
- **Wizard:** `/characters/<id>/create/<step>/` with steps `class → background → species →
  languages → equipment → abilities → choices → alignment → details → review`. Every screen: a
  progress indicator (steps done / current / needs-attention, driven by `get_state()`), the
  step's options rendered with the *existing* catalog components (class/species banner rows with
  artwork, entry renderers, links to the World detail pages for reading up), a Back / Next pair,
  and inline validation errors. Any step is reachable from the indicator once its prerequisites
  exist (e.g. *abilities* needs a background).
- **Ability screen:** method tabs (Standard array / Roll / Point buy). Standard array: assign each
  fixed value to an ability (a "suggest for my class" button applies `STANDARD_ARRAY_BY_CLASS`).
  Roll: server rolls six values (shown with the dropped die), then assign. Point buy: +/- steppers,
  live "points left", 8–15. Below: background bonus picker (+2/+1 or +1/+1/+1, only the 3 listed
  abilities, cap 20 enforced), then the resulting scores and modifiers. Primary ability of the
  class highlighted.
- **Equipment screen:** one card per source (class, background) with radio A/B(/C); group picks
  (holy symbol) show a dropdown; the gold alternative shows the amount. A running summary of items
  and gold. **Optional shop** (SRD: "you can spend the coins immediately") is Phase 6.5 — a
  searchable equipment list with cost (`Equipment.value` is copper) subtracting from the purse.
- **Review:** the computed numbers (§7) as a compact sheet, a checklist from `validation`, and
  **Finish**, which flips `status` to `complete` and redirects to the character page.
- **Navigation model** (`static/js/navigation.js`): each step transition is an ordinary page
  navigation, so Back walks back through the steps naturally inside the Characters stack, and
  tapping the Characters tab returns to the list. **Finish should collapse the wizard from the
  history** (like the account page's `data-nav="pop"`) — check whether `pop` removes one entry or
  several; a new `data-nav="reset"` (replace stack with the target) may be needed.
- **i18n:** all UI strings via `gettext` (`.po` + `.mo`; note the `msgfmt` caveat in CLAUDE.md).
  Game content already translates via modeltranslation. **New vocabulary** needing both languages:
  alignment names/blurbs, ability-method names, step names, trinkets (§10-D5), the D&D-standard
  Italian terms for the class options above (take from `glossary.md`). Measurements go through
  `apps/frontend/units.py` as elsewhere (speed 30 ft → 9 m).

---

## 6. Per-step rules (what each step validates and writes)

Written as the contract for `services/` (each bullet becomes a test). "Writes" = generated rows.

### 6.1 New character
- Name required (≤100). `start_level` 1–20 (default 1). Creates `Character(status=draft, owner)`.

### 6.2 Class
- Exactly one class from the 12. Writes `CharacterClass(level=start_level, is_starting_class=True)`.
- Grants: saving-throw proficiencies (`Class.saving_throw_abilities`); armor categories (light /
  medium / heavy / shield) and weapon categories (needs §3.2 #1) as `CharacterProficiency`;
  fixed tool proficiencies (Druid herbalism kit, Rogue thieves' tools); Hit Die.
- Skill choice from `ChoiceDefinition` (count + options; Bard = any 3, Rogue = 4 of 10).
- Level-1 features from `Feature` rows → `CharacterFeature` (excluding the un-chosen alternatives
  of an `options` node, e.g. Cleric's Protector vs Thaumaturge).
- **Proficiencies do not all come from `Class.*_proficiencies`.** [verified] Cleric *Protector*
  (Martial weapons + Heavy armor) and Druid *Warden* (Martial weapons + Medium armor) grant them
  only in feature prose, so the resolver takes proficiency grants from **both** the class row
  **and** `CLASS_CREATION_SPEC` (per chosen order). Same pattern to expect for feats/species later.
- Suggested (non-blocking) hint: show the class's primary ability + complexity from the overview.

### 6.3 Background
- Exactly one. Grants: 2 skills, the tool (fixed by name, or a pick by `EquipmentType`), the origin
  feat (`CharacterFeat`, `source="background"`), plus the feat's own sub-choices (§3.4).
- **[assumption]** No duplicate proficiencies: later pickers (class skills, Skilled, species skill)
  exclude skills the character already has. The SRD chapter doesn't spell this out; it is the
  standard 2024 expectation and avoids wasted picks. Confirm in §10-D6.

### 6.4 Species
- Exactly one. Size: if `Species.size` has two values, the player picks (stored on `Character.size`).
  Speed, darkvision (→ `CharacterSense`), traits (→ `CharacterFeature` from `Species.feature_rows`).
- Sub-choices (needs §3.2 #3): Elf lineage (+ skill Insight/Perception/Survival), Gnome lineage,
  Goliath giant ancestry, Tiefling legacy, Dragonborn ancestry (damage type), Human (+1 skill of any,
  + 1 origin feat), and the **Int/Wis/Cha casting ability** for lineage spells. Lineage changes speed
  (Wood Elf 35) and darkvision (Drow 120) — apply them.
- Species with a lineage grant cantrips now and spells at level 3/5: level-3/5 grants are applied
  when `start_level` reaches them.

### 6.5 Languages
- Common (automatic) + 2 from the 10 standard languages — chosen, or "roll for me" (1d12 table,
  re-roll on duplicate of an already-known language **[assumption]**, the SRD doesn't say).
- Class-granted extras: Druid → Druidic; Rogue → Thieves' Cant **plus one language of choice from
  the language tables** (rare languages are allowed here) [verified from the feature text].

### 6.6 Equipment
- One option per source: the class (A/B, Fighter A/B/C) and the background (A/B). Group rows require
  picking one member. Items → `CharacterInventoryItem`; gold → `CharacterCurrency` (copper split into
  gp/sp/cp). Choosing the gold-only option gives the lump sum instead of items.
- **[assumption, §10-D3]** packs (Dungeoneer's, Scholar's, ...) are expanded into their contents via
  `EquipmentPackContent` (65 rows exist) so the inventory is real; a "pack" line would hide items.
- Default equip state: proficient armor + shield + main weapon `equipped=True` (needed for AC).
- Start above level 1: add the `HIGHER_LEVEL_EQUIPMENT` gold (a roll where dice are given, stored
  once) — the chapter says the *GM* decides, so this is offered as an editable amount, not forced.

### 6.7 Ability scores
- **Standard array**: a permutation of (15,14,13,12,10,8). **Roll**: six server-rolled values (4d6
  drop lowest, 3–18). **Point buy**: each 8–15, total cost ≤ 27 (`POINT_BUY_COST`).
- Background bonus: `+2/+1` on two of the three listed abilities, or `+1/+1/+1` on all three; no
  result above 20; must pick before Finish.
- Writes `Character.strength…charisma` (final totals) **and** `CharacterAbilityScoreIncrease` rows
  (one "base" row per ability + the background rows) so the documented invariant holds: sum of rows
  per ability == the field on `Character`.

### 6.8 Alignment
- One of the 9 codes → `Character.alignment`. Evil (LE/NE/CE): show the SRD's "consult your GM"
  note; don't block.

### 6.9 Class choices (SRD step 5 "Registrare i privilegi di classe")
Driven by `CLASS_CREATION_SPEC` (§3.4): weapon masteries (only weapons that have a mastery, filtered
by the class rule and by proficiency — evaluated **after** Protector/Warden are applied, since they
change which weapons a Cleric/Druid is proficient in), fighting style feat, Divine/Primal Order
(incl. the extra cantrip and the Arcana/Religion/Nature bonus), Expertise (only
skills the character is proficient in; Rogue 2), cantrips/prepared spells filtered by
`Spell.classes` and level, wizard spellbook, invocation (prerequisites evaluated from
`OptionalFeature.prerequisite`), Rogue extra language. Counts for spellcasters come from `ClassLevel`
(never hard-coded). Writes `CharacterSpell` (with `klass`, `prepared`, `always_prepared`,
`in_spellbook`), `CharacterOptionalFeature`, `CharacterFeat`, `CharacterProficiency(level="expertise")`,
`CharacterChoice("weapon_mastery")`, and `CharacterResource` rows for L1 resources (Rage,
Second Wind, Bardic Inspiration, Lay on Hands, Favored Enemy, Arcane Recovery, Innate Sorcery) at
full uses. **Spending/recovering resources is deliberately not designed here** — that's the open
question in CLAUDE.md, and creation only needs to create them full.

### 6.10 Details
- Appearance (`Character.appearance`), notes, the six "past and present" questions as free text
  (`CharacterChoice("backstory")`), optional trinket (roll or pick, `CharacterChoice("trinket")`).

### 6.11 Hit points, Finish
- Level 1: `hit_die max + Con mod` (12/10/8/6 + Con). Levels 2..N (higher start): per level, **fixed**
  (`die//2 + 1 + Con mod`) or **rolled** (server-rolled die + Con mod, min 1), player's choice per
  level, stored in `CharacterChoice("hp_rolls")`. Sets `max_hit_points`, `current_hit_points`.
- Starting above level 1 also applies: subclass (from level 3), each ASI/feat level ≤ N
  (+2 to one / +1 to two abilities, cap 20, **or** a General feat; Epic Boon at 19), the spells,
  cantrips and class-specific picks that levels 2..N add. This is the level-up engine (Phase 7) —
  creation at level 1 does not need it.
- **Finish** runs `validation`, calls `effects.apply()` one last time, sets `status="complete"`.

---

## 7. Derived stats (`derived_stats.py`, computed, never stored)

All formulas are straight from SRD step 5 and the Equipment chapter.

- **Modifier** = `(score − 10) // 2`. **Proficiency bonus** = `2 + (total_level − 1)//4`.
- **Saving throws**: modifier (+ PB if proficient).
- **Skills** (18): ability modifier (+ PB proficient, + 2×PB expertise — never stacks beyond).
- **Passive Perception** = 10 + Perception modifier (SRD example: Wis 15 + proficiency → 14).
- **Initiative** = Dex modifier. **Speed/size/senses** from species/lineage.
- **AC**: unarmored `10 + Dex`; light `base + Dex`; medium `base + min(Dex, 2)`; heavy `base`;
  shield `+2`. Alternatives (Barbarian Unarmored Defense `10 + Dex + Con` — shield allowed; Monk
  `10 + Dex + Wis` — no armor/shield): **only one calculation applies at a time** (SRD multiclass
  rule) — take the best available. Heavy armor with Str below requirement: speed −10 ft (SRD "−3 m");
  stealth disadvantage flag; **no armor proficiency ⇒ disadvantage on Str/Dex d20 tests and no
  spellcasting** (surfaced as warnings on the Review step).
- **Attacks** for each starting weapon: melee `Str + PB`, ranged `Dex + PB` (finesse: the better of
  the two); damage adds the same modifier; PB only if proficient in the weapon's category; mastery
  property shown for the picked weapons.
- **Spellcasting** (per casting class): DC `8 + casting mod + PB`; attack `casting mod + PB`; slots
  from `ClassLevel.spell_slots` / pact columns; cantrips known; prepared count. Species-granted spells
  use their own chosen ability.
- **Hit Dice**: pool by die type across classes; spent count from `CharacterClass.hit_dice_spent`.

This service is also what the future character sheet page will read.

---

## 8. Phases

Each phase ends with: tests green (`POSTGRES_HOST=localhost POSTGRES_PORT=5462 uv run pytest`),
`ruff check .`, `manage.py check` clean, and `bash update-app.sh` (project convention).

| # | Phase | Deliverable | Notes |
|---|---|---|---|
| **0** | **Data fixes** (§3.2) | Importer fixes + new `rules` fields + migration; tests that pin them (every background has 2 skills; every class has a weapon-proficiency entry; Elf has 3 lineages; Magic Initiate variant per background; ...) | Do first, while `Character` is empty — re-import is impossible afterwards. Re-run `import_rules_data` + `import_translations` |
| **1** | **Schema** (§3.5) | `characters` migration: `owner`, `status`, `experience_points`, `is_starting_class`, `hit_dice_spent`, `CharacterSpell.klass/in_spellbook`; admin updated | No data migration needed (0 rows) |
| **2** | **Tables + class spec** (§3.3–3.4) | `builder/tables.py`, `builder/class_spec.py` + unit tests (incl. cross-checks against the DB: array-by-class vs `primary_abilities`; spec vs `ClassLevel`) | Pure Python, fast |
| **3** | **Builder engine, level 1** (§4, §6) | `creation.py`, `choices.py`, `validation.py`, `effects.py`, resolvers; `get_state()` | Snapshot-test all 12 classes through the services with several backgrounds/species, asserting HP, proficiencies, spells, inventory, gold |
| **4** | **Derived stats** (§7) | `derived_stats.py` + tests: SRD worked examples (Wis 15 + Perception → 14; Wizard/Fighter AC; Monk/Barbarian Unarmored Defense; multi-armor cases; spell DC) | |
| **5** | **Characters list + wizard UI** (§5) | `/characters/` list, `+` FAB, all 10 screens, i18n (`.po`/`.mo`), navigation stack behavior, Django-client tests per screen (happy path + validation error) | Includes the "Finish collapses history" nav work |
| **6** | **Finish + landing page** | `complete` flow, bare read-only summary at `/characters/<id>/` reusing the Review template | The full sheet ("for later") replaces it |
| **6.5** | **Optional shop** | Spend starting gold from the equipment catalog | Can slip without blocking anything |
| **7** | **Higher start level + level-up** | Start at 2–20: XP threshold, per-level HP (fixed/roll), subclass at 3, ASI/feat levels, per-level spell/cantrip/invocation/metamagic picks, `HIGHER_LEVEL_EQUIPMENT`; the same engine powers real level-up (`progression.py`, the existing `/builder/level-up*` stubs) | The engine is the same "recompute from choices" model — planned for now, built after level 1 ships |
| **8** | **Multiclass** | Prerequisite (13 in the primary ability of the new class **and** each current class — Fighter is Str *or* Dex, Monk/Paladin/Ranger are *and*); total level drives XP/PB; per-class prepared spells; combined slot table (derived from the full-caster row: full levels + ⌈½⌉ Paladin/Ranger, Pact Magic separate); Unarmored/AC one-at-a-time; Extra Attack non-stacking; only *some* starting proficiencies for a non-starting class | Needs the class rows' "multiclass" proficiency subset — check whether `db/classes.json` gives it before promising it |
| **9** | **Character page** | The full sheet (out of scope of this plan) | |

Risk order: Phase 0 (data correctness) and Phase 5's history handling are the two places most
likely to surprise; everything in between is deterministic rules code with high test leverage.

---

## 9. Testing strategy

- **Rules engine = table-driven tests, no HTTP:** for each of the 12 classes × a couple of
  backgrounds/species, run the full choice sequence through `creation` services and assert the
  persisted rows and derived numbers (not just "no exception").
- **Data-integrity tests** guard the DB against the failures found in the audit: every class has
  saves, hit die, a skill `ChoiceDefinition`, weapon proficiencies; every background has 2 skills, a
  feat, and resolvable tools; every starting-equipment row resolves (`item`/`group`/`gold`); every
  spell-list class has cantrips/level-1 spells (except Paladin/Ranger cantrips = 0).
- **Rule edge cases from the SRD text**, explicitly: ability cap 20; point buy budget/range; array
  permutation; Human size pick; Rogue expertise only on held skills; Warlock invocation prerequisite
  filtering; Wizard book 6 / prepared 4; Cleric Thaumaturge extra cantrip; unarmored + shield AC;
  heavy armor Str requirement; evil alignment warning.
- **Frontend:** Django test client per screen (renders, saves, shows validation), plus a test that
  the `+` and list are per-account, and a `test_navigation`-style check for the history collapse.
- Idempotency test: `effects.apply()` twice yields identical rows (recompute-from-choices).

---

## 10. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| **D1** | **Ownership.** `characters` has no owner ("no users app" in architecture.md), but the frontend now has password-less accounts. Should the Characters menu show *your* characters only? | Yes: nullable `owner` FK, list filtered by the signed-in user, signed-out → prompt to sign in. Old API unaffected. Cheap now, painful to retrofit |
| **D2** | **Content scope.** The DB holds far more than the SRD: 16 backgrounds (4 SRD), 11 species (9 SRD; Aasimar and Grung aren't), 77 feats (17 SRD), 48 subclasses (12 SRD). Offer everything, or only `srd=True`? | Offer everything the DB has (consistent with the World catalog), with the SRD flag available if you later want a "SRD only" toggle |
| **D3** | **Packs**: expand a starting pack into its contents, or keep it as one inventory line? | Expand (contents are real `Equipment` rows) — inventory is immediately usable |
| **D4** | **Starting level** UI: allow 1–20 at creation from day one, or ship level 1 only first? | Build the *structure* for any level, ship level 1 (Phases 0–6), then Phase 7 |
| **D5** | **Trinkets.** The Italian table is in the SRD md; the English text isn't in the repo. Options: hand-translate, source the English SRD 5.2 table, or defer | Defer (optional in the SRD: "puoi tirare"); ship as a later add-on, Italian first |
| **D6** | **No duplicate proficiencies** rule (a picker never offers what you already have) and "re-roll a duplicate 1d12 language" — the SRD chapter is silent | Adopt both as above; easy to relax |
| **D7** | **Ability-roll fairness**: allow re-generating rolled scores until the ability step is confirmed, or exactly one roll? | One roll per character, stored (the SRD gives no re-roll rule); a GM can delete the draft |
| **D8** | **Magic items** for higher-start levels (the SRD table lists counts, e.g. "1 common"): there is no magic-item catalog in `rules` | Show the allowance as text; the player records items in `notes` — no catalog work |

---

## 11. Out of scope / later

- The character sheet page, editing an existing character, resource spending and rest recovery
  (CLAUDE.md "Open design question" — unchanged; creation only creates resources at full).
- Bonus 20th-level feats ("one feat per 30,000 XP past 355,000"), combat, Epic Boon selection UI
  beyond the level-19 pick.
- Magic-item catalog; Homebrew backgrounds ("the GM may offer more backgrounds").
- Non-XPHB species beyond what's already in the DB.
