"""The chapter's tables and formulas, checked against the worked values the SRD prints."""

import pytest

from apps.builder import tables


def test_ability_modifier_matches_every_row_of_the_srd_table():
    expected = {3: -4, 4: -3, 5: -3, 6: -2, 7: -2, 8: -1, 9: -1, 10: 0, 11: 0, 12: 1, 13: 1}
    expected |= {14: 2, 15: 2, 16: 3, 17: 3, 18: 4, 19: 4, 20: 5}
    assert {score: tables.ability_modifier(score) for score in expected} == expected


def test_proficiency_bonus_matches_the_srd_progression_table():
    by_level = {1: 2, 4: 2, 5: 3, 8: 3, 9: 4, 12: 4, 13: 5, 16: 5, 17: 6, 20: 6}
    assert {lvl: tables.proficiency_bonus(lvl) for lvl in by_level} == by_level


def test_xp_table_round_trips_with_levels():
    assert tables.xp_for_level(1) == 0 and tables.xp_for_level(10) == 64_000  # the SRD's example
    assert tables.level_for_xp(0) == 1 and tables.level_for_xp(299) == 1
    assert tables.level_for_xp(300) == 2 and tables.level_for_xp(355_000) == 20
    assert tables.level_for_xp(10**7) == 20
    assert all(tables.level_for_xp(tables.xp_for_level(lv)) == lv for lv in range(1, 21))


def test_hit_points_match_the_srd_class_tables():
    # Level 1 (full die) and the fixed per-level value: barbarian d12 -> 12 / 7, fighter d10 ->
    # 10 / 6, bard d8 -> 8 / 5, wizard d6 -> 6 / 4 - each plus the Constitution modifier.
    assert [tables.hp_first_level(d, 2) for d in ("d12", "d10", "d8", "d6")] == [14, 12, 10, 8]
    assert [tables.hp_fixed_per_level(d, 0) for d in ("d12", "d10", "d8", "d6")] == [7, 6, 5, 4]
    assert tables.hp_fixed_per_level("d8", -1) == 4


def test_point_buy():
    assert tables.point_buy_cost(dict.fromkeys(tables.ABILITIES, 8)) == 0
    assert tables.POINT_BUY_COST[14] == 7  # the SRD's own example
    # The standard array costs exactly the whole 27-point budget: 9+7+5+4+2+0.
    assert (
        tables.point_buy_cost(dict(zip(tables.ABILITIES, tables.STANDARD_ARRAY, strict=True))) == 27
    )
    with pytest.raises(ValueError):
        tables.point_buy_cost({"str": 16})


def test_standard_array_by_class_uses_the_standard_array_and_favours_the_primary_ability():
    for class_id, assignment in tables.STANDARD_ARRAY_BY_CLASS.items():
        assert sorted(assignment.values(), reverse=True) == list(tables.STANDARD_ARRAY), class_id
        assert set(assignment) == set(tables.ABILITIES)


def test_language_table_covers_the_ten_standard_languages_once_each():
    assert set(tables.LANGUAGE_D12) == set(range(1, 13))
    assert len(tables.STANDARD_LANGUAGE_IDS) == 9  # + Common = the 10 standard languages
    assert tables.COMMON_LANGUAGE_ID not in tables.STANDARD_LANGUAGE_IDS


def test_alignments():
    assert len(tables.ALIGNMENTS) == 9 and set(tables.EVIL_ALIGNMENT_CODES) <= set(
        tables.ALIGNMENT_CODES
    )
