Overall architecture
┌─────────────────────────────────────────────────────┐
│                      rules                          │
│                                                     │
│  Classes · Species · Backgrounds · Feats · Spells │
│  Equipment · Features · Skills · Rules · etc.     │
│                                                     │
│                 STATIC GAME DATA                    │
└──────────────────────┬──────────────────────────────┘
                       │
                       │ referenced by
                       ▼
┌─────────────────────────────────────────────────────┐
│                    characters                       │
│                                                     │
│  Character · CharacterClass · Inventory · Spells   │
│  Choices · Abilities · Resources · Proficiencies   │
│                                                     │
│                PERSISTED GAME STATE                 │
└──────────────────────┬──────────────────────────────┘
                       │
                       │ manipulated/resolved by
                       ▼
┌─────────────────────────────────────────────────────┐
│                     builder                         │
│                                                     │
│  Creation · Choices · Validation · Level-up         │
│  Prerequisites · Effects · Derived Statistics       │
│                                                     │
│                 GAME LOGIC / ENGINE                 │
└─────────────────────────────────────────────────────┘

The key principle is:

rules describes the game. characters describes a character. builder figures out how the rules apply to a character.

1. rules app

This is your static D&D 5.5e rules/content catalog.

Nothing here should depend on a particular character.

Models
Core rules
Rule
Feature
Effect
ChoiceDefinition
Character origins
Species
Background
Feat
Classes
Class
ClassLevel
Subclass
SubclassLevel
Equipment
Equipment
EquipmentProperty
Mastery
Tool
Character mechanics
Skill
Sense
Proficiency
Language
Spells
Spell
SpellList

So the complete model tree is approximately:

rules/
├── Rule
│
├── Feature
├── Effect
├── ChoiceDefinition
│
├── Species
├── Background
├── Feat
│
├── Class
├── ClassLevel
├── Subclass
├── SubclassLevel
│
├── Equipment
├── EquipmentProperty
├── Mastery
├── Tool
│
├── Skill
├── Sense
├── Proficiency
├── Language
│
├── Spell
└── SpellList
Important relationships
Class
 ├── ClassLevel
 │     └── Feature
 │
 └── Subclass
       └── SubclassLevel
             └── Feature
Species
 └── Feature
Background
 ├── Skill
 ├── Tool
 ├── Language
 ├── Feat
 └── ChoiceDefinition
Feat
 └── Feature
       └── Effect
Equipment
 ├── EquipmentProperty
 └── Mastery
Spell
 └── SpellList
       └── Class
Rules API

I'd use one primary tag:

Rules
GET /rules/classes
GET /rules/classes/{id}
GET /rules/classes/{id}/levels
GET /rules/classes/{id}/subclasses

GET /rules/subclasses
GET /rules/subclasses/{id}

GET /rules/species
GET /rules/species/{id}

GET /rules/backgrounds
GET /rules/backgrounds/{id}

GET /rules/feats
GET /rules/feats/{id}

GET /rules/features
GET /rules/features/{id}

GET /rules/equipment
GET /rules/equipment/{id}

GET /rules/equipment-properties
GET /rules/masteries

GET /rules/skills
GET /rules/senses
GET /rules/languages
GET /rules/tools
GET /rules/proficiencies

GET /rules/spells
GET /rules/spells/{id}

GET /rules/rules
GET /rules/rules/{key}

I'd also support filters:

GET /rules/spells?class=wizard&level=3
GET /rules/feats?category=origin
GET /rules/equipment?category=weapon
GET /rules/classes?source=phb-2024

The rules app is therefore essentially read-only from the application's point of view. You populate it through fixtures/importers/admin rather than normal character API calls.

2. characters app

This contains the actual characters.

Because there is no authentication, your root concept is simply:

Character

No owner, user, or created_by.

You can have:

Aragorn
Gandalf
Legolas
My Test Character
...

and everybody can access/manage them.

Models
Main
Character
Classes / progression
CharacterClass
Ability scores
CharacterAbilityScore
Choices
CharacterChoice
Features
CharacterFeature
Proficiencies
CharacterProficiency
Senses
CharacterSense
Inventory
CharacterInventoryItem
CharacterCurrency
Spells
CharacterSpell
Resources
CharacterResource

So:

characters/
├── Character
├── CharacterClass
├── CharacterAbilityScore
├── CharacterChoice
├── CharacterFeature
├── CharacterProficiency
├── CharacterSense
├── CharacterInventoryItem
├── CharacterCurrency
├── CharacterSpell
└── CharacterResource
Character model

Conceptually:

Character
├── name
├── level
├── species
├── background
├── alignment
├── size
├── appearance
├── notes
│
├── classes[]
├── ability_scores[]
├── choices[]
├── features[]
├── proficiencies[]
├── senses[]
├── inventory[]
├── spells[]
└── resources[]

The important point is that Character references things from rules.

For example:

Character
   │
   ├── species ──────────→ rules.Species
   │
   ├── background ───────→ rules.Background
   │
   └── classes[]
             │
             └───────────→ rules.Class
Character API tags

I'd split the API into several useful tags even though they're all in the same Django app.

Characters
GET    /characters
POST   /characters

GET    /characters/{id}
PATCH  /characters/{id}
DELETE /characters/{id}

GET    /characters/{id}/sheet

The /sheet endpoint is particularly useful because the frontend shouldn't need to reconstruct the character from 20 separate requests.

It returns the resolved character sheet:

abilities
saving throws
skills
AC
HP
initiative
speed
proficiency bonus
features
feats
inventory
attacks
spells
resources
senses
etc.
Character Inventory
GET    /characters/{id}/inventory
POST   /characters/{id}/inventory

PATCH  /characters/{id}/inventory/{item_id}
DELETE /characters/{id}/inventory/{item_id}

POST   /characters/{id}/inventory/{item_id}/equip
POST   /characters/{id}/inventory/{item_id}/unequip

GET    /characters/{id}/currency
PATCH  /characters/{id}/currency
Character Spells
GET    /characters/{id}/spells
POST   /characters/{id}/spells
DELETE /characters/{id}/spells/{spell_id}

POST   /characters/{id}/spells/{spell_id}/prepare
POST   /characters/{id}/spells/{spell_id}/unprepare
Character Details
GET /characters/{id}/features
GET /characters/{id}/proficiencies
GET /characters/{id}/senses
GET /characters/{id}/resources
3. builder app

This is the most interesting app.

It doesn't primarily own data.

It owns the logic for:

What can I choose?
What must I choose?
Is this choice valid?
What does this choice grant?
What becomes available?
What becomes unavailable?
What happens when I level up?
What are my derived statistics?

I'd think of it as the D&D character engine.

Builder modules
builder/
├── api.py
├── schemas.py
│
├── services/
│   ├── builder.py
│   ├── choices.py
│   ├── validation.py
│   ├── prerequisites.py
│   ├── progression.py
│   ├── effects.py
│   └── derived_stats.py
│
└── resolvers/
    ├── class.py
    ├── species.py
    ├── background.py
    ├── feat.py
    ├── equipment.py
    ├── spell.py
    └── proficiency.py

You don't necessarily need all those files initially. They're organizational boundaries rather than separate apps.

Builder API tags
Character Builder
GET  /characters/{id}/builder

GET  /characters/{id}/builder/choices
GET  /characters/{id}/builder/choices/{key}

PUT  /characters/{id}/builder/choices/{key}

POST /characters/{id}/builder/class
POST /characters/{id}/builder/background
POST /characters/{id}/builder/species

GET  /characters/{id}/builder/ability-options
PUT  /characters/{id}/builder/ability-scores

GET  /characters/{id}/builder/starting-equipment
POST /characters/{id}/builder/starting-equipment

POST /characters/{id}/builder/finalize
Character Validation
GET  /characters/{id}/builder/validation
POST /characters/{id}/builder/validate

This should tell the frontend exactly what's wrong:

{
  "valid": false,
  "errors": [
    {
      "path": "background.ability_scores",
      "code": "incomplete",
      "message": "Choose the ability score increases."
    },
    {
      "path": "fighter.level_1.weapon_mastery",
      "code": "incomplete",
      "message": "Choose 3 weapon masteries."
    }
  ]
}

This is much better than duplicating the rules in the frontend.

Character Progression

This handles leveling.

GET  /characters/{id}/builder/level-up

POST /characters/{id}/builder/level-up/preview
POST /characters/{id}/builder/level-up/commit

For example:

GET /characters/123/builder/level-up

could return:

{
  "current_level": 4,
  "new_level": 5,

  "features": [
    "Extra Attack"
  ],

  "choices": [],

  "spell_changes": {},
  "new_resources": {}
}

For a level where choices are required:

{
  "current_level": 7,
  "new_level": 8,

  "choices": [
    {
      "key": "fighter.level_8.feat",
      "type": "feat",
      "required": true,
      "options": [...]
    }
  ]
}
The most important builder concept

I'd make this the central interface:

BuilderService.get_state(character)

It produces something like:

{
  "character": {},
  "current_step": "background",

  "steps": [
    {
      "id": "class",
      "complete": true
    },
    {
      "id": "background",
      "complete": false
    },
    {
      "id": "species",
      "complete": false
    },
    {
      "id": "abilities",
      "complete": false
    },
    {
      "id": "details",
      "complete": false
    }
  ],

  "choices": [],
  "validation": {
    "valid": false,
    "errors": []
  }
}

Your frontend can then be very dumb:

Backend says:
"Here are the choices available."

Frontend:
"Okay, I'll render them."

rather than:

Frontend:
"I know what a Fighter is.
I know when Fighting Style appears.
I know which weapons are masterable.
I know what prerequisites a feat has.
I know how multiclassing works..."

Don't put that knowledge in the frontend.

The final app boundaries

So I'd settle on:

┌─────────────────────────────────────────────┐
│                  rules                      │
│                                             │
│ Static 5.5e rules and content               │
│                                             │
│ Class                                       │
│ ClassLevel                                  │
│ Subclass                                    │
│ SubclassLevel                               │
│ Species                                     │
│ Background                                  │
│ Feat                                        │
│ Feature                                     │
│ Effect                                      │
│ ChoiceDefinition                            │
│ Equipment                                   │
│ EquipmentProperty                           │
│ Mastery                                     │
│ Spell                                       │
│ SpellList                                   │
│ Skill / Sense / Tool / Language             │
│ Proficiency / Rule                          │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│                characters                   │
│                                             │
│ Persistent character state                  │
│                                             │
│ Character                                   │
│ CharacterClass                              │
│ CharacterAbilityScore                       │
│ CharacterChoice                             │
│ CharacterFeature                            │
│ CharacterProficiency                        │
│ CharacterSense                              │
│ CharacterInventoryItem                      │
│ CharacterCurrency                           │
│ CharacterSpell                              │
│ CharacterResource                           │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│                  builder                    │
│                                             │
│ Rules engine / character creation           │
│                                             │
│ Choices                                     │
│ Prerequisites                               │
│ Validation                                  │
│ Effects                                     │
│ Derived statistics                          │
│ Leveling                                    │
│ Character resolution                        │
└─────────────────────────────────────────────┘
Compact overview
Django app	Responsibility	Models	API tags
rules	Static D&D content	Rule, Class, ClassLevel, Subclass, SubclassLevel, Feature, Effect, ChoiceDefinition, Species, Background, Feat, Equipment, EquipmentProperty, Mastery, Spell, SpellList, Skill, Sense, Language, Tool, Proficiency	Rules
characters	Persisted character state	Character, CharacterClass, CharacterAbilityScore, CharacterChoice, CharacterFeature, CharacterProficiency, CharacterSense, CharacterInventoryItem, CharacterCurrency, CharacterSpell, CharacterResource	Characters, Character Inventory, Character Spells, Character Details
builder	Creation, validation, choices, leveling, resolution	Mostly services/resolvers; ideally no major persistent models initially	Character Builder, Character Validation, Character Progression

No users app. No auth. No combat.

And I'd keep the database ownership very clean:

rules       → owns the definition of the game
characters  → owns the state of characters
builder     → owns the logic that transforms/validates that state

That's the architecture I'd use as the foundation before starting to implement the Django models.