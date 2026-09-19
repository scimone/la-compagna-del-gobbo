"""Metric display for the Italian site.

The rules data is stored in imperial units (feet, miles, pounds - the source is the English SRD),
but the Italian SRD - and so the Italian site - uses the metric system, with the SRD's own
conversions: 5 feet = 1,5 m (so feet x 0.3), 1 mile = 1,5 km, 1 pound = 0,5 kg. Everything below
converts only for display, only while Italian is the active language; English output is unchanged.

Translated paragraphs already contain metric values, so `metricize_text()` only ever matches the
English wording ("30 feet", "20-foot-radius", "5 pounds") in the paragraphs that still fall back to
English on an Italian page. It converts the *number* only, keeping the unit word in English
("9 meters", not "9 metri") - the surrounding sentence is still English, so mixing in an Italian
word there would read worse, not better; the point is that an Italian reader never has to convert
an imperial quantity in their head, not to half-translate the sentence.
"""

import re

from django.utils import translation

FEET_TO_METRES = 0.3
MILES_TO_KM = 1.5
POUNDS_TO_KG = 0.5


def is_metric() -> bool:
    return (translation.get_language() or "en").startswith("it")


def _number(value: float, decimal: str) -> str:
    """`9` -> "9", `4.5` -> "4,5" (or "4.5" with `decimal="."`); no trailing zeros."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", decimal)


def distance(feet: float, *, long: bool = False) -> str:
    """A length given in feet: `30 ft.` in English, `9 m` (or `9 metri`) in Italian."""
    if not is_metric():
        return f"{_number(feet, '.')} ft."
    metres = feet * FEET_TO_METRES
    if long:
        return f"{_number(metres, ',')} {'metro' if metres == 1 else 'metri'}"
    return f"{_number(metres, ',')} m"


def range_label(label: str) -> str:
    """A `spell_service.range_label()` value (`Self`, `Touch`, `120 feet`, `1 mile`, ...) as it
    should read on the current site."""
    if not is_metric():
        return label
    words = {"Self": "Sé", "Touch": "Contatto", "Sight": "Vista", "Unlimited": "Illimitata"}
    if label in words:
        return words[label]
    match = re.fullmatch(r"(\d+(?:\.\d+)?) (feet|foot|miles?)", label)
    if not match:
        return label
    amount = float(match.group(1))
    if match.group(2).startswith("mile"):
        return f"{_number(amount * MILES_TO_KM, ',')} chilometri"
    return distance(amount, long=True)


# --- English text that still shows on an Italian page ----------------------------------------

_FEET = re.compile(
    r"(?P<n>\d[\d,]*(?:\.\d+)?)(?P<slash>(?:/\d[\d,]*)*)(?P<sep>[- ])(?P<u>feet|foot|ft\.?)(?!\w)"
)
_MILES = re.compile(r"(?P<n>\d[\d,]*(?:\.\d+)?)(?P<sep>[- ])(?P<u>miles?)\b")
_POUNDS = re.compile(r"(?P<n>\d[\d,]*(?:\.\d+)?)(?P<sep>[- ])(?P<u>pounds?|lbs?\.?)(?!\w)")


def _convert(match: re.Match, factor: float, singular: str, plural: str, short: str) -> str:
    def one(raw: str) -> str:
        return _number(float(raw.replace(",", "")) * factor, ".")

    slash = match.groupdict().get("slash") or ""  # only `_FEET` has this group ("30/120 feet")
    numbers = [match.group("n"), *slash.split("/")[1:]]
    values = "/".join(one(n) for n in numbers)
    if match.group("u").rstrip(".") in ("ft", "lb", "lbs"):
        return f"{values} {short}"
    if match.group("sep") == "-":  # "20-foot-radius": the unit stays singular
        return f"{values}-{singular}"
    return f"{values} {singular if values == '1' else plural}"


def metricize_text(text: str) -> str:
    """English measurements in `text` converted to metric ("30 feet" -> "9 meters",
    "20-foot-radius" -> "6-meter-radius", "1 mile" -> "1.5 kilometers", "5 pounds" -> "2.5
    kilograms"), used only for English paragraphs shown on an Italian page.
    """
    if not is_metric() or not text:
        return text
    text = _FEET.sub(lambda m: _convert(m, FEET_TO_METRES, "meter", "meters", "m"), text)
    text = _MILES.sub(lambda m: _convert(m, MILES_TO_KM, "kilometer", "kilometers", "km"), text)
    return _POUNDS.sub(lambda m: _convert(m, POUNDS_TO_KG, "kilogram", "kilograms", "kg"), text)
