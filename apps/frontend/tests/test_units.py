"""Unit tests for `apps.frontend.units` - the feet/miles/pounds -> metric conversion used on the
Italian site (see that module's docstring for where the conversion factors come from).
"""

import pytest
from django.utils import translation

from apps.frontend import units


@pytest.fixture(autouse=True)
def _italian():
    with translation.override("it"):
        yield


def test_distance_converts_feet_to_metres():
    assert units.distance(30) == "9 m"
    assert units.distance(60) == "18 m"
    assert units.distance(15) == "4,5 m"  # a Monk's level-6 Unarmored Movement bonus
    assert units.distance(0) == "0 m"


def test_distance_stays_imperial_in_english():
    with translation.override("en"):
        assert units.distance(30) == "30 ft."
        assert units.distance(15) == "15 ft."


def test_range_label_converts_feet_and_miles():
    assert units.range_label("120 feet") == "36 metri"
    assert units.range_label("5 feet") == "1,5 metri"
    assert units.range_label("1 mile") == "1,5 chilometri"
    assert units.range_label("2 miles") == "3 chilometri"


def test_range_label_translates_the_word_labels():
    assert units.range_label("Self") == "Sé"
    assert units.range_label("Touch") == "Contatto"
    assert units.range_label("Unlimited") == "Illimitata"


def test_range_label_stays_english_outside_italian():
    with translation.override("en"):
        assert units.range_label("120 feet") == "120 feet"
        assert units.range_label("Self") == "Self"


def test_metricize_text_converts_feet_miles_and_pounds():
    assert units.metricize_text("You move 30 feet.") == "You move 9 meters."
    assert units.metricize_text("a 20-foot-radius Sphere") == "a 6-meter-radius Sphere"
    assert units.metricize_text("within 1 mile") == "within 1.5 kilometers"
    assert units.metricize_text("weighs 5 pounds") == "weighs 2.5 kilograms"
    assert units.metricize_text("a range of 30/120 feet") == "a range of 9/36 meters"


def test_metricize_text_handles_abbreviated_units():
    assert units.metricize_text("reach 5 ft.") == "reach 1.5 m"
    assert units.metricize_text("weighs 3 lb.") == "weighs 1.5 kg"


def test_metricize_text_leaves_non_measurements_alone():
    assert units.metricize_text("a 1d6 fire bolt") == "a 1d6 fire bolt"
    assert units.metricize_text("") == ""
    assert units.metricize_text(None) is None


def test_metricize_text_is_a_no_op_in_english():
    with translation.override("en"):
        assert units.metricize_text("You move 30 feet.") == "You move 30 feet."
